"""Import PAIMANA / OCMS monthly Flash Report PDFs into monthly CSV snapshots.

Usage::

    python -m prism.data.pdf_import                      # every PDF under data/reports/
    python -m prism.data.pdf_import path/to/report.pdf   # one file

Each report becomes ``data/real/paimana_YYYY-MM.csv`` with one row per project, which the
normal CSV ingestion then picks up. Extraction is cached: a PDF whose output CSV already
exists (and is newer) is skipped.

Supported layouts (both are text PDFs with ruled tables, read with pdfplumber):

* PAIMANA Flash Report (2025 onwards) -- "Table 6: All Ongoing Projects" with Ministry and
  Sector section rows; cells hold ``original\\n(revised)`` values and both the PAIMANA
  project code and the legacy OCMS code.
* MoSPI Flash Report "List of Tables" (2024 - early 2025) -- "Project List: Ongoing
  Projects" with State / Sector columns; cells hold ``original\\n(revised)\\n{anticipated}``.

Both layouts also carry "Completed" project tables, which provide final outcomes.
Projects are keyed on the legacy OCMS code (e.g. ``N24001425``) so they can be followed
across the OCMS -> PAIMANA transition; projects created in PAIMANA without a legacy code
use ``PM-<paimana code>``.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

from prism.config import settings

log = logging.getLogger("prism.pdf_import")

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MON3 = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
OCMS_RX = re.compile(r"\bN\d{8}\b")
PAIMANA_RX = re.compile(r"\((\d{5,7})\)")
SKIP_TITLES = ("frozen", "deleted", "dropped")


# --------------------------------------------------------------------------- small parsers
def _month(tok: str | None) -> str | None:
    """'03/2023', '3-2021', 'Aug-25', '8/2025', 'Mar 2025' -> 'YYYY-MM'."""
    if not tok:
        return None
    t = tok.strip().strip("(){}[] ").lower()
    if m := re.fullmatch(r"(\d{1,2})\s*[/-]\s*(\d{4})", t):
        mm, yy = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"([a-z]{3})[a-z]*[\s\-‐/]*(\d{2,4})", t):
        if m.group(1) not in MON3:
            return None
        mm, yy = MON3[m.group(1)], int(m.group(2))
        yy = yy + 2000 if yy < 100 else yy
    elif m := re.fullmatch(r"(\d{4})\s*[/-]\s*(\d{1,2})", t):
        yy, mm = int(m.group(1)), int(m.group(2))
    else:
        return None
    return f"{yy:04d}-{mm:02d}" if 1 <= mm <= 12 and 1990 <= yy <= 2060 else None


def _num(tok: str | None) -> float | None:
    if not tok:
        return None
    t = tok.strip().strip("(){}[] ").replace(",", "")
    if t in ("", "-", "n.a.", "N.A.", "NA"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parts(cell: str | None) -> dict[str, str]:
    """Split a multi-value cell into plain / (paren) / {brace} tokens."""
    out: dict[str, str] = {}
    for line in (cell or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        kind = "brace" if line.startswith("{") else "paren" if line.startswith("(") else "plain"
        out.setdefault(kind, line)
        out.setdefault(f"{kind}_all", "")
        out[f"{kind}_all"] += line + "\n"
    return out


def report_month(pdf, path: Path) -> str | None:
    text = " ".join((pdf.pages[i].extract_text() or "") for i in range(min(3, len(pdf.pages))))
    rx = r"(January|February|March|April|May|June|July|August|September|October|November|December)\W{0,3}(20\d\d)"
    if m := re.search(rx, text, re.I):
        return f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"
    name = path.stem.lower()
    for i, mname in enumerate(MONTHS):
        if mname[:3] in name and (y := re.search(r"20\d\d", name)):
            return f"{y.group(0)}-{i + 1:02d}"
    return None


# --------------------------------------------------------------------------- table parsing
def _columns(header: list[str | None]) -> dict[str, int] | None:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        h = (h or "").lower().replace("\n", " ")
        if "sl" in h and "no" in h and "sl" not in cols:
            cols["sl"] = i
        elif h.strip() == "state":
            cols["state"] = i
        elif h.strip() == "sector":
            cols["sector"] = i
        elif "project" in h and "name" not in cols:
            cols["name"] = i
        elif "approval" in h:
            cols["approval"] = i
        elif "doc" in h or "commissioning" in h or "completion" in h:
            cols["doc"] = i
            if "actual" in h:
                cols["actual"] = 1
        elif "cost" in h and "cost" not in cols:
            cols["cost"] = i
        elif "expenditure" in h:
            cols["exp"] = i
        elif "progress" in h:
            cols["progress"] = i
    return cols if {"name", "cost"} <= cols.keys() else None


def _parse_name(cell: str) -> dict:
    lines = [ln.strip() for ln in (cell or "").split("\n") if ln.strip()]
    text = " ".join(lines)
    ocms = OCMS_RX.search(text)
    codes = [c for c in PAIMANA_RX.findall(text)] or [ln for ln in lines if re.fullmatch(r"\d{5,7}", ln)]
    agency = None
    name_lines = []
    for ln in lines:
        if OCMS_RX.search(ln) or re.fullmatch(r"\(?\d{4,7}\)?(\s*\(.*\))*", ln) or ln.startswith("(-)"):
            continue
        if ln.startswith("(") and ln.endswith(")") and agency is None and not re.fullmatch(r"\(\d+\)", ln):
            agency = ln.strip("()").strip()
            continue
        if agency is None:
            name_lines.append(ln)
    return {"name": re.sub(r"\s+", " ", " ".join(name_lines)).strip(" -"), "agency": agency,
            "ocms_code": ocms.group(0) if ocms else None, "paimana_code": codes[0] if codes else None}


def parse_table(rows: list[list[str | None]], ctx: dict, completed: bool) -> list[dict]:
    out = []
    cols = None
    for row in rows:
        if cols is None:
            cols = _columns(row)
            continue
        cells = [(c or "").strip() for c in row]
        get = lambda k: cells[cols[k]] if k in cols and cols[k] < len(cells) else ""  # noqa: E731
        if "state" in cols and get("state"):
            ctx["state"] = get("state").replace("\n", " ")
        if "sector" in cols and get("sector"):
            ctx["sector"] = get("sector").replace("\n", " ")
        sl = get("sl") if "sl" in cols else ""
        name_cell = get("name")
        filled = [c for i, c in enumerate(cells) if c and i not in (cols.get("state"), cols.get("sector"))]
        # section rows (Ministry / Sector headings) have a single filled cell and no serial number
        if not re.fullmatch(r"\d+", sl or "") and len(filled) == 1 and name_cell and "\n" not in name_cell:
            if re.match(r"(ministry|department)\b", name_cell, re.I):
                ctx["ministry"], ctx["sector"] = name_cell, None
            else:
                ctx["sector"] = name_cell
            continue
        if not name_cell or not (get("cost") or get("exp")):
            continue
        info = _parse_name(name_cell)
        if not (info["ocms_code"] or info["paimana_code"]):
            continue
        cost, doc, appr = _parts(get("cost")), _parts(get("doc")), _parts(get("approval"))
        original_cost = _num(cost.get("plain"))
        cost_lines = [ln for ln in get("cost").split("\n") if ln.strip()]
        # revised value: {anticipated}, (revised) or -- in some 2026 reports -- a plain second line;
        # 0 / N.A. means "not revised"
        second = _num(cost_lines[1]) if len(cost_lines) > 1 else None
        revised_cost = next((v for v in (_num(cost.get("brace")), _num(cost.get("paren")), second) if v), None)
        if revised_cost is None and not (len(cost_lines) > 1 and second == 0):
            revised_cost = original_cost
        # an explicit 0 revised cost means the report left it blank: kept missing and carried
        # forward from the previous month by the loader
        doc_tokens = [t for t in re.split(r"\n", get("doc")) if t.strip()]
        if completed and cols.get("actual"):
            actual = _month(doc_tokens[0]) if doc_tokens else None
            original_doc = _month(doc_tokens[1]) if len(doc_tokens) > 1 else None
            revised_doc = (_month(doc_tokens[2]) if len(doc_tokens) > 2 else None) or actual
        else:
            actual = None
            original_doc = _month(doc.get("plain"))
            revised_doc = _month(doc.get("brace")) or _month(doc.get("paren")) or original_doc
        start = _month(appr.get("paren")) or _month(appr.get("plain"))
        progress = _num(get("progress")) if "progress" in cols else None
        # provisional key; canonical ingestion links OCMS-era and PAIMANA-era records (see link_project_ids)
        pid = f"PM-{info['paimana_code']}" if info["paimana_code"] else f"OCMS-{info['ocms_code']}"
        out.append({
            "project_id": pid, "paimana_code": info["paimana_code"], "ocms_code": info["ocms_code"],
            "project_name": info["name"], "implementing_agency": info["agency"],
            "ministry": ctx.get("ministry"), "sector": ctx.get("sector"),
            # the 2024 layout has State as a merged group cell that pdfplumber cannot place reliably,
            # so state is only trusted from the per-row State column of the PAIMANA layout
            "state": get("state").replace("\n", " ") if "state" in cols and "sector" not in cols else None,
            "approval_date": _month(appr.get("plain")), "start_date": start,
            "original_completion": original_doc, "revised_completion": revised_doc, "actual_completion": actual,
            "original_cost_cr": original_cost, "revised_cost_cr": revised_cost,
            "cumulative_expenditure_cr": _num(get("exp")),
            "physical_progress_pct": 100.0 if completed and progress is None else progress,
            "status": "Completed" if completed else "Ongoing",
        })
    return out


def link_project_ids(df: pd.DataFrame) -> pd.Series:
    """One stable ID per project across report generations.

    PAIMANA-era rows carry a PAIMANA code (unique per project) and usually the legacy OCMS
    code; OCMS-era rows carry only the OCMS code. An OCMS-era row is linked to its PAIMANA
    project when that OCMS code maps to exactly one PAIMANA code (a few legacy codes were
    split into several PAIMANA projects and stay separate)."""
    pc = df["paimana_code"].astype("string").str.replace(r"\.0$", "", regex=True)
    oc = df["ocms_code"].astype("string")
    pairs = pd.DataFrame({"pc": pc, "oc": oc}).dropna().drop_duplicates()
    counts = pairs.groupby("oc")["pc"].nunique()
    unique = pairs[pairs["oc"].isin(counts[counts == 1].index)].drop_duplicates("oc").set_index("oc")["pc"]
    linked = oc.map(unique)
    # fallback for PAIMANA rows that omit the legacy code: same original cost and similar name
    if {"original_cost_cr", "project_name"} <= set(df.columns):
        linked = linked.fillna(oc.map(_match_by_cost_and_name(df, pc, oc, set(unique.index))))
    pid = ("PM-" + pc).where(pc.notna(), ("PM-" + linked).where(linked.notna(), "OCMS-" + oc))
    return pid


def _tokens(name) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(name).lower()) if len(w) > 2 and w not in
            {"the", "and", "from", "with", "for", "project", "construction", "development", "section", "km"}}


def _match_by_cost_and_name(df: pd.DataFrame, pc: pd.Series, oc: pd.Series, done: set) -> dict:
    """OCMS code -> PAIMANA code for projects whose sanctioned cost is identical (within 0.5%) and
    whose names share at least half of their significant words; only unambiguous matches are kept."""
    old = (df.assign(oc=oc)[pc.isna() & oc.notna() & ~oc.isin(done)]
           .drop_duplicates("oc", keep="last")[["oc", "original_cost_cr", "project_name"]].dropna())
    new = (df.assign(pc=pc)[pc.notna() & oc.isna()]
           .drop_duplicates("pc", keep="last")[["pc", "original_cost_cr", "project_name"]].dropna())
    if old.empty or new.empty:
        return {}
    new = new.assign(key=new["original_cost_cr"].round(0))
    by_cost = {k: g for k, g in new.groupby("key")}
    out, used = {}, set()
    for r in old.itertuples(index=False):
        cands = [g for k in (round(r.original_cost_cr) - 1, round(r.original_cost_cr), round(r.original_cost_cr) + 1)
                 if (g := by_cost.get(k)) is not None]
        if not cands:
            continue
        cand = pd.concat(cands)
        cand = cand[(cand["original_cost_cr"] - r.original_cost_cr).abs() <= 0.005 * r.original_cost_cr]
        t = _tokens(r.project_name)
        scored = [(len(t & _tokens(c.project_name)) / max(len(t | _tokens(c.project_name)), 1), c.pc)
                  for c in cand.itertuples(index=False)]
        scored = sorted([x for x in scored if x[0] >= 0.5], reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]) and scored[0][1] not in used:
            out[r.oc] = scored[0][1]
            used.add(scored[0][1])
    return out


def harmonise(df: pd.DataFrame) -> pd.DataFrame:
    """Give OCMS-era-only projects the PAIMANA ministry / sector vocabulary.

    The 2024 reports use their own sector names (e.g. "ROAD TRANSPORT AND HIGHWAYS") and no
    ministry. For projects seen in both eras, the mapping old sector -> (ministry, sector) is
    learned and applied to projects that only appear in the older reports."""
    df = df.copy()
    has_min = df["ministry"].notna()
    latest = df[has_min].sort_values("report_month").drop_duplicates("project_id", keep="last")
    old = df[~has_min & df["sector"].notna()][["project_id", "sector"]].drop_duplicates("project_id")
    pairs = old.merge(latest[["project_id", "ministry", "sector"]], on="project_id", suffixes=("_old", ""))
    if pairs.empty:
        return df
    best = (pairs.groupby(["sector_old", "ministry", "sector"]).size().reset_index(name="n")
            .sort_values("n").drop_duplicates("sector_old", keep="last").set_index("sector_old"))
    rows = ~has_min & df["sector"].isin(best.index)
    df.loc[rows, "ministry"] = df.loc[rows, "sector"].map(best["ministry"])
    df.loc[rows, "sector"] = df.loc[rows, "sector"].map(best["sector"])
    return df


def extract(path: Path) -> pd.DataFrame:
    import pdfplumber

    rows: list[dict] = []
    with pdfplumber.open(path) as pdf:
        month = report_month(pdf, path)
        if month is None:
            raise ValueError(f"{path.name}: cannot tell which month this report is for")
        ctx: dict = {}
        section = "ongoing"
        for page in pdf.pages:
            head = (page.extract_text() or "")[:400].lower()
            if "project" not in head and "table" not in head:
                continue
            if re.search(r"table\s*[:\-]*\s*\d", head) or "project list" in head or "ongoing projects" in head:
                if any(w in head for w in SKIP_TITLES):
                    section = "skip"
                elif "completed" in head:
                    section = "completed"
                elif "ongoing" in head or "newly added" in head or "added during" in head:
                    section = "ongoing"
            if section == "skip":
                continue
            for table in page.extract_tables():
                if not table or len(table[0]) < 5:
                    continue
                # tables on continuation pages repeat the header; if not, reuse the previous header
                prev = ctx.get("_header")
                if _columns(table[0]) is not None:
                    ctx["_header"] = table[0]  # remember only genuine header rows
                elif prev and 0 <= len(prev) - len(table[0]) <= 2:
                    # continuation pages may also drop empty leading columns (State / Sector)
                    table = [prev[len(prev) - len(table[0]):], *table]
                if (c := _columns(table[0])) is None:
                    continue
                rows.extend(parse_table(table, ctx, completed=section == "completed" or bool(c.get("actual"))))
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{path.name}: no project tables recognised")
    df["report_month"] = month
    # a project can appear in several tables (e.g. all-India list and North-East list): keep the richest row
    df["_filled"] = df.notna().sum(axis=1) + (df["status"] == "Completed") * 100
    df = df.sort_values("_filled").drop_duplicates("project_id", keep="last").drop(columns="_filled")
    return df.sort_values("project_id").reset_index(drop=True)


def detect_format(pdf) -> str:
    """'paimana' (2025+), 'fr2024' (MoSPI list of tables), 'ocms' (2020-23, no physical progress) or 'other'."""
    text = " ".join((pdf.pages[i].extract_text() or "") for i in range(min(6, len(pdf.pages)))).lower()
    if "all ongoing projects" in text:
        return "paimana"
    if "project list: ongoing projects" in text or "list of tables" in text:
        return "fr2024"
    if "flash report" in text or "detail of ongoing projects" in text:
        return "ocms"
    return "other"


def _one(p: Path, out_dir: Path, force: bool) -> dict:
    import pdfplumber
    try:
        with pdfplumber.open(p) as pdf:
            month, fmt = report_month(pdf, p), detect_format(pdf)
    except Exception as e:  # noqa: BLE001
        return {"file": str(p), "status": "error", "detail": str(e)}
    if fmt not in ("paimana", "fr2024"):
        why = {"ocms": "2020-23 OCMS layout has no physical-progress column (not imported yet)",
               "other": "not a monthly Flash Report (quarterly / review / synopsis)"}[fmt]
        return {"file": str(p), "status": "skipped", "month": month, "detail": why}
    if month is None:
        return {"file": str(p), "status": "skipped", "detail": "month not found"}
    out = out_dir / f"paimana_{month}.csv"
    if out.exists() and not force and out.stat().st_mtime >= p.stat().st_mtime:
        return {"file": str(p), "status": "cached", "month": month, "output": out.name}
    try:
        df = extract(p)
    except Exception as e:  # noqa: BLE001
        return {"file": str(p), "status": "no tables", "month": month, "detail": str(e)}
    return {"file": str(p), "status": "imported", "month": month, "rows": len(df), "df": df, "output": out.name,
            "ongoing": int((df["status"] == "Ongoing").sum())}


def import_reports(src: Path | None = None, out_dir: Path | None = None, force: bool = False,
                   jobs: int = 1) -> list[dict]:
    src = Path(src or settings.data_dir / "reports")
    out_dir = Path(out_dir or settings.real_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = [src] if src.is_file() else sorted(src.rglob("*.pdf"))
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as ex:
            results = list(ex.map(_one, pdfs, [out_dir] * len(pdfs), [force] * len(pdfs)))
    else:
        results = [_one(p, out_dir, force) for p in pdfs]
    # write outputs; if two PDFs cover the same month (duplicate uploads) keep the larger extraction
    def score(r: dict) -> float:  # prefer the monthly Flash Report over a quarterly report for the same month
        quarterly = Path(r["file"]).name.upper().startswith(("QPISR", "QPSIR", "QPSR"))
        return r["rows"] * (0.5 if quarterly else 1.0)

    best: dict[str, dict] = {}
    for r in results:
        if r["status"] == "imported" and (r["month"] not in best or score(r) > score(best[r["month"]])):
            best[r["month"]] = r
    for r in results:
        if r["status"] != "imported":
            continue
        if best[r["month"]] is r:
            r["df"].to_csv(out_dir / r["output"], index=False)
            log.info("%s -> %s (%d projects)", Path(r["file"]).name, r["output"], r["rows"])
        else:
            r["status"] = "duplicate month"
        r.pop("df")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Import PAIMANA/OCMS Flash Report PDFs")
    ap.add_argument("src", nargs="?", type=Path, help="PDF file or folder (default: data/reports/)")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: data/real/)")
    ap.add_argument("--force", action="store_true", help="re-extract even if a CSV already exists")
    ap.add_argument("--jobs", type=int, default=4, help="parallel worker processes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for r in import_reports(args.src, args.out, args.force, args.jobs):
        print(f"{r['status']:>16}  {Path(r['file']).name:<45} {r.get('month', '')} {r.get('rows', '')} {r.get('detail', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
