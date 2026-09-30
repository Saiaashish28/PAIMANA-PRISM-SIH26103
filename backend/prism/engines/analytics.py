"""Comparative analytics: portfolio trends, group benchmarking, cost-escalation driver analysis.

Covers problem-statement outcomes (e) Benchmarking & Comparative Analytics and
(f) Cost Escalation Driver Analysis.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

GROUPS = {"ministry": "Ministry / Department", "sector": "Sector", "state": "State",
          "implementing_agency": "Implementing agency"}


def portfolio_trends(panel: pd.DataFrame) -> list[dict]:
    """Month-by-month portfolio totals for ongoing projects (what the Flash Report headline shows)."""
    status = panel["status_reported"] if "status_reported" in panel.columns else panel["status"]
    live = panel[status == "Ongoing"]
    g = live.groupby("report_month")
    t = pd.DataFrame({
        "projects": g["project_id"].nunique(),
        "original_cost_cr": g["original_cost_cr"].sum(),
        "revised_cost_cr": g["revised_cost_cr"].sum(),
        "expenditure_cr": g["expenditure"].sum(),
        "delayed": g["slip_months"].apply(lambda s: int((s > 0).sum())),
        "cost_overrun_projects": g["cost_growth_pct"].apply(lambda s: int((s > 0.5).sum())),
        "avg_slip_months": g["slip_months"].mean(),
        "avg_progress": g["progress"].mean(),
        "avg_risk": g["risk_composite"].mean(),
        "reported": g["physical_progress_pct"].apply(lambda s: int(s.notna().sum())),
    })
    t["cost_escalation_pct"] = (t["revised_cost_cr"] / t["original_cost_cr"] - 1) * 100
    t["delayed_pct"] = t["delayed"] / t["projects"] * 100
    # months where most projects did not report (missing report) are shown but flagged
    t["report_missing"] = t["reported"] < 0.5 * t["projects"]
    t = t.reset_index()
    t["report_month"] = t["report_month"].dt.strftime("%Y-%m")
    return t.round(3).to_dict(orient="records")


def benchmark(latest: pd.DataFrame, panel: pd.DataFrame, by: str, min_projects: int = 3) -> dict:
    """Compare groups on outcome, risk and delivery metrics; includes each group's trend."""
    if by not in GROUPS or by not in latest.columns:
        raise KeyError(by)
    live = latest[latest["status"] == "Ongoing"]
    g = live.groupby(by)
    t = pd.DataFrame({
        "ongoing": g.size(),
        "original_cost_cr": g["original_cost_cr"].sum(),
        "revised_cost_cr": g["revised_cost_cr"].sum(),
        "expenditure_cr": g["expenditure"].sum(),
        "median_slip_months": g["slip_months"].median(),
        "delayed_pct": g["slip_months"].apply(lambda s: (s > 0).mean() * 100),
        "cost_overrun_pct_projects": g["cost_growth_pct"].apply(lambda s: (s > 0.5).mean() * 100),
        "avg_progress": g["progress"].mean(),
        "avg_gap_vs_plan": g["completion_gap"].mean(),
        "avg_risk": g["risk_composite"].mean(),
        "red": g["rag"].apply(lambda s: int((s == "Red").sum())),
        "deteriorating": g["trajectory"].apply(lambda s: int(s.isin(["Deteriorating", "Rapidly Deteriorating"]).sum())),
        "avg_data_confidence": g["data_confidence"].mean(),
    })
    done = latest[latest["status"] == "Completed"].groupby(by)
    t["completed"] = done.size()
    t["completed_final_cost_growth"] = done["cost_growth_pct"].median()
    t["completed_final_slip"] = done["slip_months"].median()
    t["cost_escalation_pct"] = (t["revised_cost_cr"] / t["original_cost_cr"] - 1) * 100
    t["spend_pct"] = t["expenditure_cr"] / t["revised_cost_cr"] * 100
    t = t[t["ongoing"] >= min_projects].sort_values("revised_cost_cr", ascending=False)
    # portfolio reference values so every group can be read against the whole
    ref = {"delayed_pct": (live["slip_months"] > 0).mean() * 100,
           "cost_escalation_pct": (live["revised_cost_cr"].sum() / live["original_cost_cr"].sum() - 1) * 100,
           "median_slip_months": live["slip_months"].median(), "avg_risk": live["risk_composite"].mean(),
           "avg_progress": live["progress"].mean()}
    trend = (panel[(panel["status"] == "Ongoing") & panel[by].isin(t.index[:8])]
             .groupby([by, "report_month"]).agg(rev=("revised_cost_cr", "sum"), orig=("original_cost_cr", "sum"),
                                                slip=("slip_months", "median")).reset_index())
    trend["cost_escalation_pct"] = (trend["rev"] / trend["orig"] - 1) * 100
    trend["report_month"] = trend["report_month"].dt.strftime("%Y-%m")
    return {
        "by": by, "label": GROUPS[by], "reference": {k: round(float(v), 2) for k, v in ref.items()},
        "rows": [{"name": str(i), **{k: (None if pd.isna(v) else round(float(v), 2)) for k, v in r.items()}}
                 for i, r in t.iterrows()],
        "trend": trend[[by, "report_month", "cost_escalation_pct", "slip"]].rename(columns={by: "name"})
        .round(2).to_dict(orient="records"),
    }


def cost_drivers(latest: pd.DataFrame, global_shap: dict) -> dict:
    """Where does cost escalation come from, and what is it associated with?"""
    live = latest[latest["status"] == "Ongoing"].copy()
    live["overrun_cr"] = (live["revised_cost_cr"] - live["original_cost_cr"]).clip(lower=0)
    raw_total = float(live["overrun_cr"].sum())
    total = raw_total or 1.0

    def share(col):
        s = live.groupby(col)["overrun_cr"].sum().sort_values(ascending=False)
        return [{"name": str(k), "overrun_cr": round(float(v), 1), "share_pct": round(float(v / total * 100), 2),
                 "projects": int((live[col] == k).sum())} for k, v in s.head(12).items()]

    top = live.sort_values("overrun_cr", ascending=False)
    top["cum_share"] = top["overrun_cr"].cumsum() / total * 100
    n80 = int((top["cum_share"] < 80).sum() + 1)
    pareto = [{"project_id": r.project_id, "project_name": r.project_name, "ministry": r.ministry,
               "original_cost_cr": round(float(r.original_cost_cr), 1), "revised_cost_cr": round(float(r.revised_cost_cr), 1),
               "overrun_cr": round(float(r.overrun_cr), 1), "cost_growth_pct": round(float(r.cost_growth_pct), 1),
               "slip_months": int(r.slip_months), "cum_share": round(float(r.cum_share), 1)}
              for r in top.head(20).itertuples()]

    # time-cost link: does delay go with cost escalation?
    bins = pd.cut(live["slip_months"], [-1, 0, 12, 24, 48, 1e9], labels=["On time", "1-12 m", "13-24 m", "25-48 m", ">48 m"])
    link = live.groupby(bins, observed=False).agg(projects=("project_id", "size"),
                                                  mean_cost_growth=("cost_growth_pct", "mean"),
                                                  median_cost_growth=("cost_growth_pct", "median"),
                                                  share_with_overrun=("cost_growth_pct", lambda s: (s > 0.5).mean() * 100))
    link = [{"delay_band": str(k), **{c: (None if pd.isna(v) else round(float(v), 2)) for c, v in r.items()}}
            for k, r in link.iterrows()]

    # interpretable regression (statsmodels OLS with robust errors): cost growth ~ project characteristics
    reg = None
    d = live[["cost_growth_pct", "slip_months", "log_original_cost", "elapsed_frac", "progress", "sector"]].dropna()
    d = d[d["cost_growth_pct"].between(-50, 500)]
    if len(d) > 60 and d["cost_growth_pct"].std() > 1e-6:
        top_sectors = d["sector"].value_counts().index[:8]
        d["sector_grp"] = np.where(d["sector"].isin(top_sectors), d["sector"], "Other")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = smf.ols("cost_growth_pct ~ slip_months + log_original_cost + elapsed_frac + progress + C(sector_grp)",
                        data=d).fit(cov_type="HC3")
        labels = {"slip_months": "Schedule slippage (per month)", "log_original_cost": "Project size (x10 sanctioned cost)",
                  "elapsed_frac": "Share of original schedule elapsed", "progress": "Physical progress (per pp)"}
        coefs = []
        for name, coef in m.params.items():
            if name == "Intercept":
                continue
            label = labels.get(name, name.replace("C(sector_grp)[T.", "Sector: ").rstrip("]"))
            ci = m.conf_int().loc[name]
            coefs.append({"term": label, "coef": round(float(coef), 3), "ci_low": round(float(ci[0]), 3),
                          "ci_high": round(float(ci[1]), 3), "p_value": round(float(m.pvalues[name]), 4),
                          "significant": bool(m.pvalues[name] < 0.05)})
        reg = {"n": int(m.nobs), "r2": round(float(m.rsquared), 3), "coefficients": coefs,
               "baseline_sector": sorted(set(d["sector_grp"]) - {c["term"].replace("Sector: ", "") for c in coefs})[:1],
               "note": "Association, not causation: coefficients are % points of cost growth per unit, "
                       "controlling for the other terms (heteroskedasticity-robust HC3 errors)."}
    return {
        "total_overrun_cr": round(raw_total, 1), "projects_with_overrun": int((live["overrun_cr"] > 0).sum()),
        "projects_for_80pct": n80 if raw_total > 0 else None, "by_ministry": share("ministry"), "by_sector": share("sector"),
        "by_state": share("state"), "pareto": pareto, "time_cost_link": link, "regression": reg,
        "model_drivers": global_shap.get("cost_12", [])[:12],
    }


# --------------------------------------------------------------------------- live feed: what changed
def month_changes(panel: pd.DataFrame, latest: pd.DataFrame, top: int = 40) -> dict:
    """What the latest monthly report changed versus each project's previous report."""
    month = panel["report_month"].max()
    rep = panel[panel["reported"]] if "reported" in panel.columns else panel
    rep = rep.sort_values(["project_id", "report_month"])
    months = sorted(rep["report_month"].unique())
    prev_month = months[-2] if len(months) > 1 else None
    info = latest.set_index("project_id")[["project_name", "ministry", "priority_index", "rag"]]

    g = rep.groupby("project_id", sort=False)
    cur = g.tail(1)
    cur = cur[cur["report_month"] == month].set_index("project_id")
    prev = g.nth(-2).set_index("project_id").reindex(cur.index)

    def rows(ids, extra):
        out = []
        for pid in ids:
            i = info.loc[pid] if pid in info.index else None
            out.append({"project_id": pid, "project_name": None if i is None else i["project_name"],
                        "ministry": None if i is None else i["ministry"],
                        "rag": None if i is None else i["rag"], **extra(pid)})
        return out

    both = prev["report_month"].notna()
    d_cost = (cur["revised_cost_cr"] - prev["revised_cost_cr"]).where(both)
    cost_rev = d_cost[(d_cost > 0.01 * prev["revised_cost_cr"])].sort_values(ascending=False)
    slip = ((cur["revised_completion"].dt.year - prev["revised_completion"].dt.year) * 12
            + cur["revised_completion"].dt.month - prev["revised_completion"].dt.month).where(both)
    slips = slip[slip > 0].sort_values(ascending=False)
    live_cur = cur["status"] == "Ongoing"
    stalled = cur.index[both & live_cur & ((cur["progress"] - prev["progress"]).abs() <= 0.01) & (cur["progress"] < 99.5)]

    first_seen = panel.groupby("project_id")["report_month"].min()
    new_ids = first_seen[first_seen == month].index
    done_ids = cur.index[cur["status"] == "Completed"]
    last_seen = panel.groupby("project_id")["report_month"].max()
    left_ids = last_seen[(last_seen == prev_month)].index if prev_month is not None else []

    return {
        "month": pd.Timestamp(month).strftime("%Y-%m"),
        "previous_month": pd.Timestamp(prev_month).strftime("%Y-%m") if prev_month is not None else None,
        "summary": {"reported": int(len(cur)), "cost_revisions": int(len(cost_rev)),
                    "cost_added_cr": round(float(cost_rev.sum()), 1), "schedule_slips": int(len(slips)),
                    "months_added": int(slips.sum()), "completed": int(len(done_ids)), "new": int(len(new_ids)),
                    "left_list": int(len(left_ids)), "no_progress": int(len(stalled))},
        "cost_revisions": rows(cost_rev.index[:top], lambda p: {
            "from_cr": round(float(prev.at[p, "revised_cost_cr"]), 1), "to_cr": round(float(cur.at[p, "revised_cost_cr"]), 1),
            "added_cr": round(float(cost_rev[p]), 1)}),
        "schedule_slips": rows(slips.index[:top], lambda p: {
            "from": prev.at[p, "revised_completion"].strftime("%Y-%m"), "to": cur.at[p, "revised_completion"].strftime("%Y-%m"),
            "months": int(slips[p])}),
        "completed": rows(list(done_ids[:top]), lambda p: {}),
        "new": rows(list(new_ids[:top]), lambda p: {"original_cost_cr": round(float(cur.at[p, "original_cost_cr"]), 1)
                                                    if p in cur.index else None}),
    }


def change_events(ch: dict, max_items: int = 12) -> list[dict]:
    """Feed events for a monthly report's changes (summary first, then the largest items)."""
    m, s = ch["month"], ch["summary"]
    label = pd.Timestamp(m + "-01").strftime("%b %Y")
    ev = [{"kind": "data", "severity": "notice", "month": m, "title": f"{label} report loaded",
           "detail": f"{s['reported']} projects reported: {s['cost_revisions']} cost revisions (+Rs {s['cost_added_cr']:,.0f} Cr), "
                     f"{s['schedule_slips']} schedule slips (+{s['months_added']} months in total), {s['completed']} completed, "
                     f"{s['new']} newly added.", "data": s}]
    for r in ch["cost_revisions"][:max_items // 2]:
        ev.append({"kind": "report", "severity": "high" if r["added_cr"] >= 1000 else "notice", "month": m,
                   "project_id": r["project_id"], "title": f"Cost revised +Rs {r['added_cr']:,.0f} Cr: {r['project_name']}",
                   "detail": f"Revised cost Rs {r['from_cr']:,.0f} Cr -> Rs {r['to_cr']:,.0f} Cr ({r['ministry']})."})
    for r in ch["schedule_slips"][:max_items // 2]:
        ev.append({"kind": "report", "severity": "high" if r["months"] >= 12 else "notice", "month": m,
                   "project_id": r["project_id"], "title": f"Completion slipped {r['months']} months: {r['project_name']}",
                   "detail": f"Anticipated completion {r['from']} -> {r['to']} ({r['ministry']})."})
    for r in ch["completed"][:3]:
        ev.append({"kind": "report", "severity": "info", "month": m, "project_id": r["project_id"],
                   "title": f"Completed: {r['project_name']}", "detail": r["ministry"]})
    return ev


def state_diff(old_latest: pd.DataFrame | None, new_latest: pd.DataFrame, old_warn: pd.DataFrame | None,
               new_warn: pd.DataFrame, max_items: int = 15) -> list[dict]:
    """Model-side escalations between two pipeline states (after a retrain on new data)."""
    if old_latest is None:
        return []
    old = old_latest.set_index("project_id")
    new = new_latest[new_latest["status"] == "Ongoing"].set_index("project_id")
    common = new.index.intersection(old.index)
    ev = []
    became_red = [p for p in common if new.at[p, "rag"] == "Red" and old.at[p, "rag"] != "Red"]
    became_red.sort(key=lambda p: -float(new.at[p, "priority_index"]))
    for p in became_red[:max_items]:
        ev.append({"kind": "warning", "severity": "critical", "project_id": p,
                   "title": f"Now Red: {new.at[p, 'project_name']}",
                   "detail": f"Was {old.at[p, 'rag']}; composite risk {old.at[p, 'risk_composite']:.1f} -> "
                             f"{new.at[p, 'risk_composite']:.1f}, trajectory {new.at[p, 'trajectory']}."})
    rapid = [p for p in common if new.at[p, "trajectory"] == "Rapidly Deteriorating"
             and old.at[p, "trajectory"] != "Rapidly Deteriorating" and p not in became_red]
    for p in rapid[:max_items // 2]:
        ev.append({"kind": "warning", "severity": "high", "project_id": p,
                   "title": f"Rapidly deteriorating: {new.at[p, 'project_name']}",
                   "detail": f"Risk velocity {new.at[p, 'risk_velocity']:+.1f} points/month."})
    if old_warn is not None and len(new_warn):
        key = lambda w: set(zip(w["project_id"], w["dimension"], w["severity"]))  # noqa: E731
        fresh = key(new_warn[new_warn["severity"] == "Critical"]) - key(old_warn)
        for pid, dim, _ in sorted(fresh)[:max_items // 2]:
            if pid in new.index and pid not in became_red:
                ev.append({"kind": "warning", "severity": "high", "project_id": pid,
                           "title": f"New critical {dim} warning: {new.at[pid, 'project_name']}",
                           "detail": "Expected within 3 months."})
    if became_red or rapid:
        ev.insert(0, {"kind": "warning", "severity": "high",
                      "title": f"{len(became_red)} project(s) turned Red, {len(rapid)} started deteriorating rapidly",
                      "detail": "Compared with the previous model run."})
    return ev
