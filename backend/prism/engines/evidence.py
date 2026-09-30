"""Evidence Packager.

Every number an administrator (or the LLM) sees about a project comes from one
evidence package: a list of atomic, citable items ``E1..En`` built directly
from pipeline outputs. The dashboard, the assistant and the grounding validator
all read the same package, so there is no drift between a chart and a sentence.
"""
from __future__ import annotations

import pandas as pd

from prism.config import DIMENSIONS, HORIZONS
from prism.engines.analogues import summarise
from prism.engines.explain import drivers
from prism.engines.features import ALL_FEATURES
from prism.engines.forecasting import forecast_project
from prism.engines.portfolio import ministry_label
from prism.engines.remarks import CATEGORY_LABELS
from prism.engines.trajectory import DIM_LABEL

# Driver -> suggested review pathway (decision support, not an automated decision).
PATHWAYS = {
    "bn_land_6m": ("state_coordination", "Escalate land / Right-of-Way issues to a Chief Secretary-level coordination review"),
    "land_acquisition_friction_score": ("state_coordination", "Escalate land / Right-of-Way issues to a Chief Secretary-level coordination review"),
    "bn_clearance_6m": ("clearance_expedited", "Seek expedited forest / environmental clearance through the inter-ministerial committee"),
    "bn_contractor_6m": ("contractor_action", "Review contractor capacity and mobilisation; issue a performance notice if warranted"),
    "contractor_credit_score": ("contractor_action", "Review contractor financial health and mobilisation"),
    "bn_funding_6m": ("funds_released", "Review fund-flow and release of pending bills"),
    "spend_progress_gap": ("funds_released", "Reconcile financial vs physical progress and review the revised cost estimate"),
    "expenditure_ratio": ("funds_released", "Review sanctioned-cost headroom; a revised cost estimate may be imminent"),
    "bn_litigation_6m": ("pmg_review", "Fast-track legal / arbitration matters through a PMG review"),
    "velocity_3m": ("site_inspection", "Commission a targeted site inspection to verify progress and remobilisation"),
    "velocity_6m": ("site_inspection", "Commission a targeted site inspection to verify progress and remobilisation"),
    "velocity_ratio": ("site_inspection", "Commission a targeted site inspection to verify progress and remobilisation"),
    "completion_gap": ("pmg_review", "Take up in PRAGATI / PMG review with a milestone-level recovery plan"),
    "slip_months": ("pmg_review", "Re-baseline the schedule with milestone-level monitoring"),
    "months_left": ("pmg_review", "Re-baseline the schedule with milestone-level monitoring"),
    "bottleneck_streak": ("pmg_review", "Take up the unresolved bottleneck in a PRAGATI / PMG review"),
    "bn_design_geo_6m": ("pmg_review", "Freeze scope / design changes and review geotechnical risk"),
}


def review_pathways(driver_sets: dict[str, list[dict]], data_confidence: float) -> list[dict]:
    """Suggested review pathways from the factors currently raising each risk dimension."""
    pathways, seen = [], set()
    for dim in DIMENSIONS:
        for d in driver_sets[dim]:
            if d["shap"] > 0 and d["feature"] in PATHWAYS and PATHWAYS[d["feature"]][1] not in seen:
                seen.add(PATHWAYS[d["feature"]][1])
                pathways.append({"action_type": PATHWAYS[d["feature"]][0], "text": PATHWAYS[d["feature"]][1],
                                 "because": f"{d['label']} is raising {DIM_LABEL[dim].lower()} risk"})
    if data_confidence < 70:
        pathways.insert(0, {"action_type": "site_inspection", "text": "Verify the reported data before acting on the scores",
                            "because": "data confidence is low"})
    return pathways


def action_queue(state, recent_ids: set[str], limit: int = 20) -> list[dict]:
    """Highest-priority ongoing projects without a recent decision, each with its top review pathway."""
    live = state.latest[(state.latest["status"] == "Ongoing") & ~state.latest["project_id"].isin(recent_ids)]
    out = []
    for pos, r in live.sort_values("priority_index", ascending=False).head(limit).iterrows():
        x_row = state.latest.loc[pos, ALL_FEATURES]
        ds = {dim: drivers(state.shap_latest[(dim, 6)][pos], x_row, top_n=4) for dim in DIMENSIONS}
        pw = review_pathways(ds, float(r["data_confidence"]))
        w = state.warnings[state.warnings["project_id"] == r["project_id"]]
        out.append({"project_id": r["project_id"], "project_name": r["project_name"], "ministry": r["ministry"],
                    "rag": r["rag"], "trajectory": r["trajectory"], "priority_index": round(float(r["priority_index"]), 1),
                    "risk_composite": round(float(r["risk_composite"]), 1),
                    "warnings": [f"{x.warning} within {x.horizon_months} months" for x in w.itertuples()][:3],
                    "pathways": pw[:3]})
    return out


class Evidence:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, category: str, label: str, value, text: str, unit: str | None = None) -> str:
        eid = f"E{len(self.items) + 1}"
        self.items.append({"id": eid, "category": category, "label": label, "value": value, "unit": unit, "text": text})
        return eid

    def as_dict(self, **extra) -> dict:
        return {"items": self.items, **extra}


def _m(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %Y")


def project_evidence(state, project_id: str, interventions: list[dict] | None = None) -> dict:
    r = state.latest_row(project_id)
    hist = state.history(project_id)
    ev = Evidence()
    as_of = _m(r["report_month"])

    ev.add("facts", "Project", r["project_name"],
           f"{r['project_name']} ({project_id}) is a {r['sector']} project of the {ministry_label(r['ministry'])} in {r['state']}, "
           f"status {r['status']}, last reported {as_of}.")
    ev.add("facts", "Sanctioned vs revised cost", round(float(r["revised_cost_cr"]), 1),
           f"Original sanctioned cost is Rs {r['original_cost_cr']:,.1f} Cr; current revised cost is Rs {r['revised_cost_cr']:,.1f} Cr, "
           f"a cost growth of {r['cost_growth_pct']:.1f}% after {int(r['n_cost_revisions'])} revision(s).", "Rs Cr")
    ev.add("facts", "Expenditure", round(float(r["expenditure"]), 1),
           f"Cumulative expenditure is Rs {r['expenditure']:,.1f} Cr, {r['expenditure_ratio']:.1f}% of the revised cost.", "Rs Cr")
    ev.add("facts", "Physical progress", round(float(r["progress"]), 1),
           f"Physical progress is {r['progress']:.1f}% against {r['expected_progress']:.1f}% expected under the original plan "
           f"(gap {r['completion_gap']:.1f} pp).", "%")
    ev.add("facts", "Schedule", int(r["slip_months"]),
           f"Original completion was {_m(r['original_completion'])}; revised completion is {_m(r['revised_completion'])}, "
           f"a slippage of {int(r['slip_months'])} months over {int(r['n_schedule_revisions'])} revision(s).", "months")
    ev.add("facts", "Progress velocity", round(float(r["velocity_3m"]), 2),
           f"Progress velocity is {r['velocity_3m']:.2f} pp/month over the last 3 months and {r['velocity_6m']:.2f} pp/month over 6 months; "
           f"finishing on the revised date needs {r['required_velocity']:.2f} pp/month.", "pp/month")

    ev.add("trust", "Data confidence", float(r["data_confidence"]),
           f"Data confidence is {r['data_confidence']:.1f}/100 ({r['confidence_grade']}): {int(r['staleness_months'])} month(s) stale, "
           f"{int(r['n_contradictions'])} contradiction(s) and {int(r['n_anomalies'])} anomaly flag(s) in the reporting history.", "/100")

    ev.add("risk", "Composite risk", round(float(r["risk_composite"]), 1),
           f"Composite risk score is {r['risk_composite']:.1f}/100 (RAG: {r['rag']}); risk trajectory is {r['trajectory']} "
           f"with risk velocity {r['risk_velocity']:+.2f} points/month.", "/100")
    for dim in DIMENSIONS:
        ps = {h: 100 * float(r[f"p_{dim}_{h}"]) for h in HORIZONS}
        ev.add("risk", f"{DIM_LABEL[dim]} probability", round(ps[6], 1),
               f"{DIM_LABEL[dim]} probability: {ps[3]:.1f}% within 3 months, {ps[6]:.1f}% within 6 months, "
               f"{ps[12]:.1f}% within 12 months (dimension score {r[f'risk_{dim}']:.1f}/100).", "%")

    w = state.warnings[state.warnings["project_id"] == project_id]
    for x in w.itertuples(index=False):
        prob = f" (probability {100 * x.probability:.1f}% vs alert threshold {100 * x.threshold:.1f}%)" if pd.notna(x.probability) else ""
        ev.add("warning", x.warning, x.horizon_months,
               f"{x.severity} early warning: {x.warning} expected within {x.horizon_months} months{prob}.", "months")

    pos = state.latest.index[state.latest["project_id"] == project_id][0]
    x_row = state.latest.loc[pos, ALL_FEATURES]
    driver_sets = {}
    for dim in DIMENSIONS:
        ds = drivers(state.shap_latest[(dim, 6)][pos], x_row, top_n=4)
        driver_sets[dim] = ds
        up = [d for d in ds if d["shap"] > 0][:3]
        if up:
            ev.add("drivers", f"{DIM_LABEL[dim]} drivers", len(up),
                   f"Main factors raising {DIM_LABEL[dim].lower()} risk: " +
                   "; ".join(f"{d['label']} = {d['value']}" for d in up) + ".")

    fc = forecast_project(hist)
    if fc["projected_completion"]:
        ev.add("forecast", "Projected completion", fc["additional_slip_months"],
               f"At the current pace, completion is projected for {pd.Timestamp(fc['projected_completion']).strftime('%b %Y')}, "
               f"{fc['additional_slip_months']} months relative to the revised completion date.", "months")
    else:
        ev.add("forecast", "Projected completion", None,
               "Progress velocity is too low to project a completion date at the current pace.")
    if r["status"] == "Ongoing":
        ev.add("forecast", "Final cost growth range", round(float(r["cost_q50"]), 1),
               f"Predicted final cost growth: {r['cost_q50']:.1f}% (80% range {r['cost_q10']:.1f}% to {r['cost_q90']:.1f}%).", "%")
        ev.add("forecast", "Final time overrun range", round(float(r["time_q50"]), 1),
               f"Predicted final time overrun: {r['time_q50']:.1f} months (80% range {r['time_q10']:.1f} to {r['time_q90']:.1f}).", "months")

    analogues = state.analogues.query(r)
    summ = summarise(analogues)
    if summ:
        ev.add("analogues", "Historical analogues", summ["median_final_cost_growth_pct"],
               f"{summ['n']} similar completed projects, matched at the same stage, finished with a median cost growth of "
               f"{summ['median_final_cost_growth_pct']:.1f}% and median time overrun of {summ['median_final_slip_months']:.1f} months; "
               f"{summ['share_slip_over_12m']:.1f}% of them slipped more than 12 months.", "%")

    rem = hist[hist["remarks"].notna()].tail(3)
    for x in rem.itertuples(index=False):
        ev.add("remarks", f"Remark {_m(x.report_month)}", CATEGORY_LABELS.get(x.bottleneck, x.bottleneck),
               f"Remark ({_m(x.report_month)}): \"{x.remarks}\" [classified: {CATEGORY_LABELS.get(x.bottleneck, x.bottleneck)}].")
    if int(r["bottleneck_streak"]) > 0:
        ev.add("remarks", "Unresolved bottleneck", int(r["bottleneck_streak"]),
               f"The current bottleneck has been reported for {int(r['bottleneck_streak'])} consecutive month(s).", "months")

    for iv in (interventions or [])[:3]:
        ev.add("interventions", "Past intervention", iv.get("delta_risk"),
               f"Intervention ({iv['intervention_month']}): {iv['description']} -- outcome: {iv.get('outcome', 'n/a')}"
               + (f", risk change {iv['delta_risk']:+.1f} points." if iv.get("delta_risk") is not None else "."))

    pathways = review_pathways(driver_sets, float(r["data_confidence"]))

    return ev.as_dict(scope="project", project_id=project_id, as_of=as_of, drivers=driver_sets, forecast=fc,
                      analogues=analogues, pathways=pathways[:4])


def portfolio_evidence(state) -> dict:
    L = state.latest
    live = L[L["status"] == "Ongoing"]
    ev = Evidence()
    as_of = _m(state.as_of)
    rag = live["rag"].value_counts()
    ev.add("portfolio", "Portfolio size", int(len(L)),
           f"PRISM monitors {len(L)} projects as of {as_of}: {len(live)} ongoing and {int((L['status'] == 'Completed').sum())} completed.")
    ev.add("portfolio", "Portfolio cost", round(float(live["revised_cost_cr"].sum()), 1),
           f"Ongoing projects: total original cost Rs {live['original_cost_cr'].sum():,.1f} Cr vs revised cost "
           f"Rs {live['revised_cost_cr'].sum():,.1f} Cr ({(live['revised_cost_cr'].sum() / live['original_cost_cr'].sum() - 1) * 100:.1f}% "
           f"escalation); expenditure Rs {live['expenditure'].sum():,.1f} Cr.", "Rs Cr")
    ev.add("portfolio", "RAG distribution", int(rag.get("Red", 0)),
           f"Of ongoing projects, {int(rag.get('Red', 0))} are Red, {int(rag.get('Amber', 0))} Amber and {int(rag.get('Green', 0))} Green.")
    traj = live["trajectory"].value_counts()
    ev.add("portfolio", "Trajectories", int(traj.get("Rapidly Deteriorating", 0)),
           f"{int(traj.get('Rapidly Deteriorating', 0))} projects are rapidly deteriorating, {int(traj.get('Deteriorating', 0))} deteriorating, "
           f"{int(traj.get('Stable', 0))} stable and {int(traj.get('Improving', 0))} improving.")
    w = state.warnings
    for h in HORIZONS:
        n = int(w.loc[w["horizon_months"] == h, "project_id"].nunique())
        ev.add("warnings", f"{h}-month warnings", n, f"{n} projects carry an early warning at the {h}-month horizon.")
    for x in live.sort_values("priority_index", ascending=False).head(8).itertuples(index=False):
        ev.add("priority", x.project_id, round(float(x.priority_index), 1),
               f"{x.project_id} ({x.project_name}, {x.ministry}) has priority index {x.priority_index:.1f}, composite risk "
               f"{x.risk_composite:.1f}/100, RAG {x.rag}, trajectory {x.trajectory}.")
    for b in state.portfolio["bottleneck_frequency"]["overall"][:4]:
        ev.add("bottlenecks", b["label"], b["projects"],
               f"'{b['label']}' affected {b['projects']} projects in the last 12 months.")
    try:  # what the latest monthly report changed
        from prism.engines.analytics import month_changes
        ch = month_changes(state.panel, state.latest, top=3)
        sm = ch["summary"]
        ev.add("changes", "Latest report", sm["reported"],
               f"The {_m(ch['month'] + '-01')} report covered {sm['reported']} projects: {sm['schedule_slips']} schedule slips "
               f"(+{sm['months_added']} months in total), {sm['cost_revisions']} cost revisions (+Rs {sm['cost_added_cr']:,.0f} Cr), "
               f"{sm['completed']} completed and {sm['new']} newly added.")
        for r in ch["schedule_slips"][:3]:
            ev.add("changes", r["project_id"], r["months"],
                   f"{r['project_id']} ({r['project_name']}) slipped {r['months']} months, to {_m(r['to'] + '-01')}.", "months")
        for r in ch["cost_revisions"][:3]:
            ev.add("changes", r["project_id"], r["added_cr"],
                   f"{r['project_id']} ({r['project_name']}) cost revised by +Rs {r['added_cr']:,.0f} Cr.", "Rs Cr")
    except Exception:  # noqa: BLE001 -- evidence stays usable without this section
        pass
    for s in state.portfolio["by_sector"][:3]:
        ev.add("sectors", s["name"], s["avg_risk"],
               f"Sector {s['name']}: average composite risk {s['avg_risk']:.1f}/100 across {s['ongoing']} ongoing projects, "
               f"cost escalation {s['cost_escalation_pct']:.1f}%.")
    for m in state.portfolio["by_ministry"][:3]:
        ev.add("ministries", m["name"], m["avg_risk"],
               f"{ministry_label(m['name'])}: average composite risk {m['avg_risk']:.1f}/100, {m['red']} Red projects, "
               f"{m['deteriorating']} deteriorating.")
    for p in state.portfolio["patterns"]:
        ev.add("patterns", "Systemic pattern", None, p)
    return ev.as_dict(scope="portfolio", as_of=as_of)
