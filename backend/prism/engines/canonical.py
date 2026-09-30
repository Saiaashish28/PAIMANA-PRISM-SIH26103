"""Canonical Project Model: loads raw CUF exports and joins them into one monthly panel.

Two data sources are supported:

* ``data/real/``  -- real PAIMANA/OCMS exports dropped in by the user (used whenever present)
* ``data/raw/``   -- the bundled synthetic dataset (fallback / demo)

Real exports are messy, so ingestion is forgiving:

* CSV or Excel (``.csv``, ``.xlsx``, ``.xls``);
* column names are normalised and common PAIMANA spellings are mapped
  (e.g. "Anticipated Cost (Rs Cr)" -> ``revised_cost_cr``);
* every file in the folder that is not the master / macro / interventions file is
  treated as a monthly snapshot and concatenated, so one file per reporting month works;
  a file without a ``report_month`` column takes its month from the file name
  (e.g. ``2026-04.xlsx`` or ``PAIMANA_April_2026.csv``);
* if there is no ``project_master`` file, project attributes are taken from the monthly rows;
* dates in most common formats, numbers with commas / "Rs" / "%" are accepted;
* ``status`` and map coordinates are derived when missing.
"""
from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from prism.config import settings
from prism.engines.remarks import classify_series

log = logging.getLogger("prism.ingest")

MASTER_STEM = "project_master"
MACRO_STEM = "macro_indicators"
INTERVENTIONS_STEM = "interventions_history"
EXTENSIONS = (".csv", ".xlsx", ".xls")

REQUIRED_MASTER = {"project_id", "project_name", "ministry", "sector", "state", "start_date",
                   "original_completion", "original_cost_cr"}
REQUIRED_MONTHLY = {"project_id", "report_month", "physical_progress_pct", "cumulative_expenditure_cr",
                    "revised_cost_cr", "revised_completion"}
MASTER_OPTIONAL = ["approval_date", "latitude", "longitude", "implementing_agency", "contractor_name", "contractor_credit_score",
                   "land_acquisition_friction_score", "weather_geopolitical_risk_index"]

# normalised header -> canonical column
ALIASES = {
    "project_id": ["id", "project_code", "proj_id", "ocms_id", "paimana_id", "project_no", "sl_no_project_id"],
    "project_name": ["name", "project", "name_of_project", "name_of_the_project", "project_title"],
    "ministry": ["ministry_department", "ministry_dept", "department", "ministry_name"],
    "sector": ["sub_sector", "sector_name", "infrastructure_sector"],
    "state": ["state_ut", "location", "state_name", "states"],
    "start_date": ["date_of_start", "start", "sanction_date", "date_of_sanction", "date_of_approval", "approval_date"],
    "original_completion": ["original_date_of_completion", "original_completion_date", "original_doc",
                            "scheduled_completion", "original_scheduled_completion", "date_of_completion_original"],
    "original_cost_cr": ["original_cost", "sanctioned_cost", "approved_cost", "original_cost_rs_cr",
                         "original_cost_rs_crore", "original_cost_in_rs_crore", "original_cost_in_crore"],
    "report_month": ["month", "reporting_month", "as_on", "as_on_date", "report_date", "period", "month_year"],
    "physical_progress_pct": ["physical_progress", "progress", "physical_progress_percent", "progress_pct",
                              "physical_progress_in_percent", "physical_progress_percentage"],
    "cumulative_expenditure_cr": ["expenditure", "cumulative_expenditure", "expenditure_incurred",
                                  "cum_expenditure", "expenditure_rs_cr", "cumulative_expenditure_rs_cr",
                                  "expenditure_till_date", "total_expenditure"],
    "revised_cost_cr": ["revised_cost", "anticipated_cost", "latest_approved_cost", "revised_cost_rs_cr",
                        "anticipated_cost_rs_cr", "latest_cost", "revised_anticipated_cost"],
    "revised_completion": ["revised_date_of_completion", "anticipated_date_of_completion", "anticipated_completion",
                           "revised_completion_date", "expected_completion", "anticipated_doc", "revised_doc"],
    "remarks": ["remark", "reasons_for_delay", "reason_for_delay", "bottlenecks", "status_remarks", "comments"],
    "status": ["project_status", "current_status"],
    "implementing_agency": ["agency", "executing_agency", "implementing_agency_name"],
    "contractor_name": ["contractor", "contractor_name_s"],
    "latitude": ["lat"],
    "longitude": ["lon", "lng", "long"],
}
_ALIAS_LOOKUP = {a: canon for canon, alist in ALIASES.items() for a in [canon, *alist]}

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# State centroids for the map when real data has no coordinates.
STATE_CENTROIDS = {
    "andhra pradesh": (15.9, 79.7), "arunachal pradesh": (28.2, 94.7), "assam": (26.2, 92.9), "bihar": (25.1, 85.3),
    "chhattisgarh": (21.3, 81.9), "goa": (15.3, 74.1), "gujarat": (22.3, 71.2), "haryana": (29.1, 76.1),
    "himachal pradesh": (31.9, 77.1), "jammu & kashmir": (33.7, 75.1), "jammu and kashmir": (33.7, 75.1),
    "jharkhand": (23.6, 85.3), "karnataka": (15.3, 75.7), "kerala": (10.5, 76.3), "ladakh": (34.2, 77.6),
    "madhya pradesh": (23.5, 78.6), "maharashtra": (19.7, 75.7), "manipur": (24.7, 93.9), "meghalaya": (25.5, 91.4),
    "mizoram": (23.2, 92.9), "nagaland": (26.2, 94.6), "odisha": (20.9, 84.8), "punjab": (31.1, 75.3),
    "rajasthan": (27.0, 74.2), "sikkim": (27.5, 88.5), "tamil nadu": (11.1, 78.7), "telangana": (18.1, 79.0),
    "tripura": (23.9, 91.9), "uttar pradesh": (26.8, 80.9), "uttarakhand": (30.1, 79.0), "west bengal": (22.9, 87.9),
    "delhi": (28.6, 77.2), "puducherry": (11.9, 79.8), "chandigarh": (30.7, 76.8),
    "andaman & nicobar islands": (11.7, 92.7), "lakshadweep": (10.6, 72.6),
}
INDIA_CENTRE = (22.5, 80.0)


# --------------------------------------------------------------------------- source selection
def find_file(folder: Path, stem: str) -> Path | None:
    for ext in EXTENSIONS:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def monthly_files(folder: Path) -> list[Path]:
    """Every data file in the folder except master / macro / interventions (and anything in sub-folders)."""
    skip = {MASTER_STEM, MACRO_STEM, INTERVENTIONS_STEM}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in EXTENSIONS and p.stem not in skip and not p.name.startswith(("~", ".")))


def has_data(folder: Path) -> bool:
    return folder.is_dir() and bool(monthly_files(folder))


def resolve_source() -> tuple[str, Path]:
    """('real', data/real) when real files are present (or forced), else ('synthetic', data/raw)."""
    mode = settings.data_source
    if mode == "real" or (mode == "auto" and has_data(settings.real_dir)):
        return "real", settings.real_dir
    return "synthetic", settings.raw_dir


def source_files(raw_dir: Path) -> list[Path]:
    files = monthly_files(raw_dir) if raw_dir.is_dir() else []
    for stem in (MASTER_STEM, MACRO_STEM, INTERVENTIONS_STEM):
        if p := find_file(raw_dir, stem):
            files.append(p)
    return files


# --------------------------------------------------------------------------- parsing helpers
def _norm(col: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(col).strip().lower()).strip("_")


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_excel(path)
    df = df.dropna(how="all")
    rename = {}
    exact = {_norm(c) for c in df.columns}
    for c in df.columns:
        n = _norm(c)
        target = _ALIAS_LOOKUP.get(n)
        if target is None:  # also try without a trailing unit, e.g. "revised_cost_rs_cr" -> "revised_cost"
            target = _ALIAS_LOOKUP.get(re.sub(r"_(in_)?(rs_)?(cr|crore|crores)$|_(percent|pct|in_percent)$", "", n))
        target = target or n
        if target != n and target in exact:  # the file has the exact column: an alias must not replace it
            target = n
        rename[c] = target
    df = df.rename(columns=rename)
    return df.loc[:, ~df.columns.duplicated()]


def _to_number(s: pd.Series) -> pd.Series:
    if s.dtype.kind in "if":
        return s.astype(float)
    cleaned = s.astype("string").str.replace(r"[,₹%]|rs\.?|crore|cr", "", regex=True, case=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def _to_month(s: pd.Series) -> pd.Series:
    """Parse dates in any common format and snap to the first of the month."""
    if pd.api.types.is_datetime64_any_dtype(s):
        d = s
    else:
        txt = s.astype("string").str.strip()
        d = pd.to_datetime(txt, errors="coerce", format="%Y-%m-%d")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %Y", "%B %Y", "%b-%Y", "%b-%y", "%m/%Y", "%Y/%m/%d"):
            d = d.fillna(pd.to_datetime(txt, errors="coerce", format=fmt))
        if d.isna().any():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                d = d.fillna(pd.to_datetime(txt, errors="coerce", dayfirst=True))
    return d.dt.to_period("M").dt.to_timestamp()


def month_from_filename(name: str) -> pd.Timestamp | None:
    n = name.lower()
    if m := re.search(r"(20\d{2})[-_ .]?(0[1-9]|1[0-2])(?!\d)", n):
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
    if m := re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_ .]*(20\d{2})", n):
        return pd.Timestamp(int(m.group(2)), MONTHS[m.group(1)], 1)
    return None


# --------------------------------------------------------------------------- loading
def load_raw(raw_dir: Path | None = None) -> dict:
    raw_dir = Path(raw_dir or resolve_source()[1])
    notes: list[str] = []
    files = monthly_files(raw_dir)
    if not files:
        raise ValueError(f"No monthly snapshot files found in {raw_dir}")

    parts, named = [], []
    for f in files:
        df = _read(f)
        if "report_month" not in df.columns:
            m = month_from_filename(f.name)
            if m is None:
                raise ValueError(f"{f.name}: no report_month column and no month in the file name "
                                 f"(name it like 2026-04.csv or April_2026.xlsx)")
            df["report_month"] = f"{m:%Y-%m}"
            named.append(f.name)
        df["_source_file"] = f.name
        parts.append(df)
    monthly = pd.concat(parts, ignore_index=True)
    if named:
        notes.append(f"Report month taken from the file name for {len(named)} file(s), e.g. {named[0]}")
    is_flash = {"paimana_code", "ocms_code"} <= set(monthly.columns)
    if is_flash:  # imported Flash Report PDFs
        from prism.data.pdf_import import harmonise, link_project_ids
        monthly["project_id"] = link_project_ids(monthly)
        monthly = harmonise(monthly)
        notes.append("Flash Report extracts: OCMS-era and PAIMANA-era records linked by project code")
    if "project_id" not in monthly.columns:
        raise ValueError("Monthly data has no project_id column. See data/real/README.md for accepted names.")
    monthly["project_id"] = monthly["project_id"].astype("string").str.strip()
    monthly["report_month"] = _to_month(monthly["report_month"])

    master_path = find_file(raw_dir, MASTER_STEM)
    if master_path is not None:
        master = _read(master_path)
    else:
        attrs = [c for c in [*REQUIRED_MASTER, *MASTER_OPTIONAL] if c in monthly.columns and c != "project_id"]
        master = monthly.sort_values("report_month").groupby("project_id", as_index=False)[attrs].last()
        notes.append("No project_master file: project attributes taken from the monthly files")

    missing_master = sorted(REQUIRED_MASTER - set(master.columns))
    missing_monthly = sorted(REQUIRED_MONTHLY - set(monthly.columns))
    if missing_master or missing_monthly:
        msg = []
        if missing_master:
            msg.append(f"project details missing columns {missing_master}")
        if missing_monthly:
            msg.append(f"monthly data missing columns {missing_monthly}")
        raise ValueError("; ".join(msg) + ". See data/real/README.md for the expected columns and accepted names.")

    # ---- clean master
    master["project_id"] = master["project_id"].astype("string").str.strip()
    master = master.drop_duplicates("project_id", keep="last")
    for c in ("start_date", "original_completion"):
        master[c] = _to_month(master[c])
    master["original_cost_cr"] = _to_number(master["original_cost_cr"])
    # reports print "N.A." for some original completion dates: fall back to the earliest reported one
    no_doc = master["original_completion"].isna()
    if no_doc.any() and "revised_completion" in monthly.columns:
        first_doc = (monthly.assign(_d=_to_month(monthly["revised_completion"])).sort_values("report_month")
                     .dropna(subset=["_d"]).groupby("project_id")["_d"].first())
        master.loc[no_doc, "original_completion"] = master.loc[no_doc, "project_id"].map(first_doc)
        filled = int(master.loc[no_doc, "original_completion"].notna().sum())
        if filled:
            notes.append(f"{filled} project(s) without an original completion date use their earliest reported completion date")
    for c in ("project_name", "ministry", "sector", "state"):
        master[c] = master[c].astype("string").str.strip().fillna("Unknown")
    no_start = master["start_date"].isna()
    if no_start.any():
        if "approval_date" in master.columns:  # sanction/approval date is the next best start marker
            master["approval_date"] = _to_month(master["approval_date"])
            master.loc[no_start, "start_date"] = master.loc[no_start, "approval_date"]
        still = master["start_date"].isna()
        first_seen = monthly.groupby("project_id")["report_month"].min()
        master.loc[still, "start_date"] = master.loc[still, "project_id"].map(first_seen)
        notes.append(f"{int(no_start.sum())} project(s) without a start date use their approval date "
                     f"({int(no_start.sum() - still.sum())}) or first reporting month ({int(still.sum())})")
    bad = master["start_date"].isna() | master["original_completion"].isna() | ~(master["original_cost_cr"] > 0)
    if bad.any():
        notes.append(f"Dropped {int(bad.sum())} project(s) with unreadable start/completion date or cost: "
                     + ", ".join(master.loc[bad, "project_id"].head(10)))
        master = master[~bad]
    for c in ("latitude", "longitude"):
        master[c] = _to_number(master[c]) if c in master.columns else np.nan
    cent = master["state"].str.lower().map(STATE_CENTROIDS)
    jitter = np.random.default_rng(0).normal(0, 0.6, (len(master), 2))
    fill_lat = cent.map(lambda v: v[0] if isinstance(v, tuple) else INDIA_CENTRE[0]) + jitter[:, 0]
    fill_lon = cent.map(lambda v: v[1] if isinstance(v, tuple) else INDIA_CENTRE[1]) + jitter[:, 1]
    if master["latitude"].isna().any():
        notes.append("Map coordinates approximated from state centroids where latitude/longitude were missing")
    master["latitude"] = master["latitude"].fillna(fill_lat.round(4))
    master["longitude"] = master["longitude"].fillna(fill_lon.round(4))
    for c in ("implementing_agency", "contractor_name"):
        master[c] = master[c].astype("string").fillna("Not reported") if c in master.columns else "Not reported"
    for c in ("contractor_credit_score", "land_acquisition_friction_score", "weather_geopolitical_risk_index"):
        if c in master.columns:
            master[c] = _to_number(master[c])

    # ---- clean monthly
    monthly["revised_completion"] = _to_month(monthly["revised_completion"])
    for c in ("physical_progress_pct", "cumulative_expenditure_cr", "revised_cost_cr"):
        monthly[c] = _to_number(monthly[c])
    if monthly["physical_progress_pct"].max() <= 1.0:
        monthly["physical_progress_pct"] *= 100
        notes.append("Physical progress looked like fractions (0-1); converted to percent")
    if "remarks" not in monthly.columns:
        monthly["remarks"] = pd.NA
        notes.append("No remarks column: bottleneck analysis will be empty")
    bad = monthly["report_month"].isna()
    if bad.any():
        notes.append(f"Dropped {int(bad.sum())} monthly row(s) with an unreadable report month")
        monthly = monthly[~bad]
    unknown = ~monthly["project_id"].isin(master["project_id"])
    if unknown.any():
        notes.append(f"Dropped {int(unknown.sum())} monthly row(s) for {monthly.loc[unknown, 'project_id'].nunique()} "
                     "project(s) not present in the project details")
        monthly = monthly[~unknown]
    dup = monthly.duplicated(["project_id", "report_month"], keep="last")
    if dup.any():
        notes.append(f"{int(dup.sum())} duplicate project-month row(s): kept the last one")
        monthly = monthly[~dup]
    # revised values fall back to the originals when not reported
    orig = monthly["project_id"].map(master.set_index("project_id")["original_cost_cr"])
    monthly["revised_cost_cr"] = monthly["revised_cost_cr"].fillna(
        monthly.groupby("project_id")["revised_cost_cr"].ffill()).fillna(orig)
    orig_done = monthly["project_id"].map(master.set_index("project_id")["original_completion"])
    monthly["revised_completion"] = monthly["revised_completion"].fillna(
        monthly.sort_values("report_month").groupby("project_id")["revised_completion"].ffill()).fillna(orig_done)
    if "status" in monthly.columns:
        st = monthly["status"].astype("string").str.lower()
        monthly["status"] = np.where(st.str.contains("complet", na=False), "Completed", "Ongoing")
    else:
        monthly["status"] = np.where(monthly["physical_progress_pct"] >= 99.5, "Completed", "Ongoing")
    monthly = monthly.sort_values(["project_id", "report_month"])
    if is_flash:
        monthly, extra = _flash_report_lifecycle(monthly)
        notes.extend(extra)
    monthly = _fill_month_gaps(monthly, notes)
    keep_monthly = [c for c in monthly.columns if c not in master.columns or c == "project_id"]
    monthly = monthly[keep_monthly]

    # ---- optional files
    macro = None
    if p := find_file(raw_dir, MACRO_STEM):
        macro = _read(p).rename(columns={"report_month": "month"})  # "month" is a monthly-file alias
        macro["month"] = _to_month(macro["month"])
        macro = macro.dropna(subset=["month"])
    iv_cols = ["project_id", "intervention_month", "action_type", "description", "authority"]
    iv = pd.DataFrame(columns=iv_cols)
    if p := find_file(raw_dir, INTERVENTIONS_STEM):
        iv = _read(p)
        iv["intervention_month"] = _to_month(iv["intervention_month"])
        iv["project_id"] = iv["project_id"].astype("string").str.strip()
        for c in iv_cols:
            if c not in iv.columns:
                iv[c] = "other" if c == "action_type" else ""
        iv = iv.dropna(subset=["intervention_month"])[iv_cols]

    for n in notes:
        log.info("ingest: %s", n)
    return {"master": master.reset_index(drop=True), "monthly": monthly.reset_index(drop=True), "macro": macro,
            "interventions": iv, "notes": notes, "files": [f.name for f in source_files(raw_dir)]}


def _fill_month_gaps(monthly: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """Put every project on a complete monthly timeline between its first and last report.

    Months without a report become rows with missing values: the Data Trust engine flags them
    and forward-fills the cumulative series, and every "n months ahead" feature/label is then a
    true calendar offset rather than "n reports ahead"."""
    parts, added = [], 0
    for pid, g in monthly.groupby("project_id", sort=False):
        full = pd.date_range(g["report_month"].min(), g["report_month"].max(), freq="MS")
        if len(full) != len(g):
            g = g.set_index("report_month").reindex(full).rename_axis("report_month").reset_index()
            added += int(g["project_id"].isna().sum())
            g["project_id"] = pid
            for c in ("revised_cost_cr", "revised_completion", "status", "status_reported"):
                if c in g.columns:
                    g[c] = g[c].ffill()
        parts.append(g)
    if added:
        notes.append(f"{added} project-month(s) had no report (e.g. a month's report missing); "
                     "kept as gaps and treated as not reported")
    return pd.concat(parts, ignore_index=True)


def _flash_report_lifecycle(monthly: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """In Flash Reports a project leaves the ongoing list when it is completed (or dropped).
    Projects missing from the latest report without a 'Completed' row are closed at their last
    report: Completed if they were >= 95% complete, otherwise Dropped (not counted as ongoing)."""
    last_month = monthly["report_month"].max()
    monthly["status_reported"] = monthly["status"]  # what the report itself said (used for trends)
    last = monthly.groupby("project_id").tail(1)
    gone = last[(last["report_month"] < last_month) & (last["status"] == "Ongoing")]
    done = gone["physical_progress_pct"].fillna(0) >= 95
    idx_done, idx_drop = gone.index[done], gone.index[~done]
    monthly.loc[idx_done, "status"] = "Completed"
    monthly.loc[idx_drop, "status"] = "Dropped"
    notes = []
    if len(gone):
        notes.append(f"{len(gone)} project(s) left the ongoing list without a completion entry: "
                     f"{int(done.sum())} marked Completed (>= 95% progress), {int((~done).sum())} marked Dropped")
    return monthly, notes


def build_canonical(raw: dict) -> pd.DataFrame:
    master, monthly, macro = raw["master"], raw["monthly"], raw["macro"]
    df = monthly.merge(master, on="project_id", how="inner", validate="many_to_one")
    df = df.sort_values(["project_id", "report_month"]).reset_index(drop=True)

    # Remarks are free text -> derive the bottleneck category ourselves.
    df["bottleneck"] = classify_series(df["remarks"])

    if macro is not None and "cci_yoy_pct" in macro.columns:
        df = df.merge(macro[["month", "cci_yoy_pct"]].rename(columns={"month": "report_month"}), on="report_month", how="left")
    for col, default in [("cci_yoy_pct", 5.0), ("contractor_credit_score", 60.0),
                         ("land_acquisition_friction_score", 40.0), ("weather_geopolitical_risk_index", 30.0)]:
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[col].median() if df[col].notna().any() else default)
    df["month_index"] = df.groupby("project_id").cumcount()
    return df
