"""Portfolio intelligence: systemic bottlenecks, sector/ministry fingerprints, contractor benchmarks."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from prism.engines.remarks import CATEGORY_LABELS  # noqa: F401 -- re-exported for the pipeline


def ministry_label(name) -> str:
    """'Railways' -> 'Ministry of Railways'; names that already say Ministry/Department are kept."""
    name = str(name)
    return name if re.match(r"(ministry|department|dept)\b", name, re.I) else f"Ministry of {name}"


def _active(bn: pd.Series) -> pd.Series:
    return ~bn.isin(["none", "unknown"])


# Delivery-issue signals derived from the reported figures, used when a source carries no remarks
# (e.g. Flash Report tables). One primary signal per project-month, in order of severity.
SIGNAL_LABELS = {
    "stalled": "Progress stalled (no movement for 3 months)",
    "overdue": "Past its anticipated completion date",
    "recent_slip": "Schedule revised in the last 6 months",
    "recent_cost_revision": "Cost revised in the last 6 months",
    "spend_ahead": "Spending well ahead of physical progress",
    "behind_plan": "More than 25 pp behind the original plan",
    "none": "No issue signal",
}


def remarks_available(panel: pd.DataFrame) -> bool:
    return bool(_active(panel["bottleneck"]).any())


def with_issue_signals(panel: pd.DataFrame, latest: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace remark-based bottleneck categories with figure-derived issue signals (+ streaks)."""
    p = panel.copy()
    live = (p["status"] == "Ongoing") & (p["progress"] < 99.5)
    conds = [
        live & p["reported"] & (p["velocity_3m"] <= 0.05) & (p["elapsed_months"] >= 4),
        live & (p["months_left"] < 0),
        live & (p["n_schedule_revisions"] > 0) & (p["months_since_schedule_revision"] <= 6),
        live & (p["n_cost_revisions"] > 0) & (p["months_since_cost_revision"] <= 6),
        live & (p["spend_progress_gap"] > 15),
        live & (p["completion_gap"] > 25),
    ]
    p["bottleneck"] = np.select(conds, list(SIGNAL_LABELS)[:6], default="none")
    active = p["bottleneck"] != "none"
    same = p["bottleneck"].eq(p.groupby("project_id")["bottleneck"].shift(1))
    run_id = (~same).groupby(p["project_id"]).cumsum()
    p["bottleneck_streak"] = np.where(active, p.groupby([p["project_id"], run_id]).cumcount() + 1, 0)
    last = p.groupby("project_id").tail(1).set_index("project_id")
    L = latest.copy()
    L["bottleneck"] = L["project_id"].map(last["bottleneck"]).fillna("none")
    L["bottleneck_streak"] = L["project_id"].map(last["bottleneck_streak"]).fillna(0).astype(int)
    return p, L


def bottleneck_frequency(f: pd.DataFrame, months: int = 12, labels: dict = CATEGORY_LABELS) -> dict:
    cutoff = f["report_month"].max() - pd.DateOffset(months=months)
    rec = f[(f["report_month"] > cutoff) & _active(f["bottleneck"])]
    overall = (rec.groupby("bottleneck")["project_id"].nunique().sort_values(ascending=False))
    by = {}
    for dim in ("ministry", "sector", "state"):
        t = rec.groupby([dim, "bottleneck"])["project_id"].nunique().unstack(fill_value=0)
        by[dim] = [{"name": idx, **{k: int(v) for k, v in row.items()}} for idx, row in t.iterrows()]
    return {
        "window_months": months,
        "overall": [{"category": k, "label": labels.get(k, k), "projects": int(v)} for k, v in overall.items()],
        "by": by,
    }


def recurring_bottlenecks(f: pd.DataFrame, latest: pd.DataFrame, min_streak: int = 4, labels: dict = CATEGORY_LABELS) -> list[dict]:
    rec = latest[(latest["status"] == "Ongoing") & (latest["bottleneck_streak"] >= min_streak)]
    return [{"project_id": r.project_id, "project_name": r.project_name, "ministry": r.ministry, "sector": r.sector,
             "state": r.state, "category": r.bottleneck, "label": labels.get(r.bottleneck, r.bottleneck),
             "months_unresolved": int(r.bottleneck_streak)}
            for r in rec.sort_values("bottleneck_streak", ascending=False).itertuples(index=False)]


def bottleneck_impact(f: pd.DataFrame, labels: dict = CATEGORY_LABELS) -> list[dict]:
    """Which bottlenecks most often precede overruns? Lift of 6-month event rates when a
    bottleneck category is reported vs months with no bottleneck (historical, all projects)."""
    rows = []
    lab = f[f["y_cost_6"].notna()]
    base = lab[lab["bottleneck"] == "none"]
    b_cost, b_sched, b_stall = base["y_cost_6"].mean(), base["y_schedule_6"].mean(), base["y_implementation_6"].mean()
    for cat, grp in lab[_active(lab["bottleneck"])].groupby("bottleneck"):
        if len(grp) < 30:
            continue
        rows.append({"category": cat, "label": labels.get(cat, cat), "n_reports": int(len(grp)),
                     "cost_event_rate": round(float(grp["y_cost_6"].mean()), 3),
                     "schedule_event_rate": round(float(grp["y_schedule_6"].mean()), 3),
                     "stall_rate": round(float(grp["y_implementation_6"].mean()), 3),
                     "cost_lift": round(float(grp["y_cost_6"].mean() / max(b_cost, 1e-6)), 2),
                     "schedule_lift": round(float(grp["y_schedule_6"].mean() / max(b_sched, 1e-6)), 2),
                     "stall_lift": round(float(grp["y_implementation_6"].mean() / max(b_stall, 1e-6)), 2)})
    return sorted(rows, key=lambda r: -(r["cost_lift"] + r["schedule_lift"] + r["stall_lift"]))


def fingerprints(latest: pd.DataFrame, by: str) -> list[dict]:
    live = latest[latest["status"] == "Ongoing"]
    allp = latest.groupby(by).agg(
        projects=("project_id", "size"), completed=("status", lambda s: int((s == "Completed").sum())),
        original_cost_cr=("original_cost_cr", "sum"), revised_cost_cr=("revised_cost_cr", "sum"),
        median_slip=("slip_months", "median"))
    lv = live.groupby(by).agg(
        ongoing=("project_id", "size"), avg_risk=("risk_composite", "mean"), avg_cost_risk=("risk_cost", "mean"),
        avg_schedule_risk=("risk_schedule", "mean"), avg_implementation_risk=("risk_implementation", "mean"),
        red=("rag", lambda s: int((s == "Red").sum())), amber=("rag", lambda s: int((s == "Amber").sum())),
        deteriorating=("trajectory", lambda s: int(s.isin(["Deteriorating", "Rapidly Deteriorating"]).sum())),
        avg_velocity=("velocity_6m", "mean"))
    t = allp.join(lv, how="left").fillna(0)
    t["cost_escalation_pct"] = (t["revised_cost_cr"] / t["original_cost_cr"] - 1) * 100
    t = t.sort_values("avg_risk", ascending=False)
    return [{"name": idx, **{k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else int(v))
                             for k, v in row.items()}} for idx, row in t.iterrows()]


def entity_benchmark(latest: pd.DataFrame, key: str, min_projects: int = 2) -> list[dict]:
    """Performance of implementing agencies / contractors across all their projects."""
    if key not in latest.columns:
        return []
    known = latest[~latest[key].astype("string").isin(["Not reported", "Unknown"]) & latest[key].notna()]
    if known.empty:
        return []
    g = known.groupby(key)
    t = g.agg(projects=("project_id", "size"), ongoing=("status", lambda s: int((s == "Ongoing").sum())),
              completed=("status", lambda s: int((s == "Completed").sum())),
              avg_slip=("slip_months", "mean"), avg_cost_growth=("cost_growth_pct", "mean"),
              avg_risk=("risk_composite", "mean"), revised_cost_cr=("revised_cost_cr", "sum"),
              red=("rag", lambda s: int((s == "Red").sum())),
              delayed_share=("slip_months", lambda s: float((s > 0).mean() * 100)))
    t = t[t["projects"] >= min_projects].sort_values("avg_risk", ascending=False)
    return [{"name": idx, **{k: round(float(v), 2) for k, v in row.items()}} for idx, row in t.iterrows()]


def systemic_patterns(latest: pd.DataFrame, impact: list[dict], freq: dict) -> list[str]:
    """Short plain-language findings computed from the tables above (no LLM involved)."""
    out = []
    live = latest[latest["status"] == "Ongoing"]
    if impact:
        top = impact[0]
        out.append(f"'{top['label']}' is the issue most associated with future overruns: projects showing it saw "
                   f"{top['schedule_lift']}x the baseline 6-month slippage rate and {top['cost_lift']}x the cost-escalation rate.")
    if freq["overall"]:
        top = freq["overall"][0]
        out.append(f"'{top['label']}' affected {top['projects']} projects in the last {freq['window_months']} months, "
                   f"the most widespread issue in the portfolio.")
    sec = live.groupby("sector")["risk_composite"].mean().sort_values(ascending=False)
    if len(sec):
        out.append(f"{sec.index[0]} carries the highest average composite risk ({sec.iloc[0]:.1f}/100) among sectors "
                   f"with ongoing projects.")
    det = live[live["trajectory"].isin(["Deteriorating", "Rapidly Deteriorating"])]
    if len(det):
        m = det["ministry"].value_counts()
        out.append(f"{len(det)} ongoing projects are on a deteriorating risk trajectory; {m.iloc[0]} of them are under "
                   f"the {ministry_label(m.index[0])}.")
    return out
