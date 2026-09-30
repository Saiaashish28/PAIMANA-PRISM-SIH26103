"""Point-in-time feature builder + early-warning labels.

Every feature for month *t* uses only information reported up to *t*, so the
models learn exactly what an administrator would have known at that time.
Labels look *forward* h in {3, 6, 12} months:

  cost            cost growth rises by >= COST_EVENT_PP points (a new escalation)
  schedule        revised completion slips by >= SCHEDULE_EVENT_MONTHS more months
  implementation  progress over the window < STALL_RATIO x the project's planned
                  average pace (a stall / bottleneck)

Labels are left NaN when the future window is not yet observed (censored).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from prism.config import COST_EVENT_PP, HORIZONS, SCHEDULE_EVENT_MONTHS, STALL_RATIO

CUF_FEATURES = [
    "elapsed_frac", "progress", "completion_gap", "velocity_3m", "velocity_6m", "velocity_accel",
    "velocity_ratio", "cost_growth_pct", "n_cost_revisions", "months_since_cost_revision",
    "slip_months", "n_schedule_revisions", "months_since_schedule_revision", "months_left",
    "expenditure_ratio", "spend_progress_gap", "log_original_cost",
    "bottleneck_active", "bottleneck_streak", "bottleneck_months_6m", "bn_land_6m", "bn_clearance_6m",
    "bn_contractor_6m", "bn_funding_6m", "bn_litigation_6m", "bn_design_geo_6m", "report_quality_6m",
]
NON_CUF_FEATURES = [
    # external variables (supplied when available; constant otherwise, which the models ignore)
    "contractor_credit_score", "land_acquisition_friction_score", "weather_geopolitical_risk_index", "cci_yoy_pct",
    # portfolio context: track record of *other* projects, as known at the same month
    "peer_agency_slip", "peer_agency_cost_growth", "peer_state_slip", "peer_sector_cost_growth",
]
ALL_FEATURES = CUF_FEATURES + NON_CUF_FEATURES

FEATURE_LABELS = {
    "elapsed_frac": "Share of original schedule elapsed",
    "progress": "Physical progress (%)",
    "completion_gap": "Gap vs planned progress (pp)",
    "velocity_3m": "Progress velocity, last 3 months (pp/month)",
    "velocity_6m": "Progress velocity, last 6 months (pp/month)",
    "velocity_accel": "Change in progress velocity",
    "velocity_ratio": "Achieved vs required velocity",
    "cost_growth_pct": "Cost growth so far (%)",
    "n_cost_revisions": "Number of cost revisions",
    "months_since_cost_revision": "Months since last cost revision",
    "slip_months": "Schedule slippage so far (months)",
    "n_schedule_revisions": "Number of schedule revisions",
    "months_since_schedule_revision": "Months since last schedule revision",
    "months_left": "Months left to revised completion",
    "expenditure_ratio": "Expenditure / sanctioned cost (%)",
    "spend_progress_gap": "Financial vs physical progress gap (pp)",
    "log_original_cost": "Project size (log sanctioned cost)",
    "bottleneck_active": "Bottleneck reported this month",
    "bottleneck_streak": "Consecutive months with a bottleneck",
    "bottleneck_months_6m": "Bottleneck months in last 6",
    "bn_land_6m": "Land/RoW issues in last 6 months",
    "bn_clearance_6m": "Clearance issues in last 6 months",
    "bn_contractor_6m": "Contractor issues in last 6 months",
    "bn_funding_6m": "Funding issues in last 6 months",
    "bn_litigation_6m": "Litigation in last 6 months",
    "bn_design_geo_6m": "Design/geology issues in last 6 months",
    "report_quality_6m": "Reporting completeness, last 6 months",
    "contractor_credit_score": "Contractor credit score (non-CUF)",
    "land_acquisition_friction_score": "Regional land-acquisition friction (non-CUF)",
    "weather_geopolitical_risk_index": "Weather / geopolitical exposure (non-CUF)",
    "cci_yoy_pct": "Construction cost inflation YoY (non-CUF)",
    "peer_agency_slip": "Implementing agency's slippage on other projects (context)",
    "peer_agency_cost_growth": "Implementing agency's cost growth on other projects (context)",
    "peer_state_slip": "Slippage of other projects in the same state (context)",
    "peer_sector_cost_growth": "Cost growth of other projects in the same sector (context)",
}

_BN_GROUPS = {
    "bn_land_6m": {"land_acquisition", "utility_shifting"},
    "bn_clearance_6m": {"forest_clearance"},
    "bn_contractor_6m": {"contractor_issues"},
    "bn_funding_6m": {"funding_delay"},
    "bn_litigation_6m": {"litigation", "law_and_order"},
    "bn_design_geo_6m": {"design_scope", "geology_weather"},
}


def _months_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a.dt.year - b.dt.year) * 12 + (a.dt.month - b.dt.month)


def _since_last_event(event: pd.Series, groups: pd.Series) -> pd.Series:
    """Months since the last True in ``event`` within each group (capped at 120)."""
    idx = pd.Series(np.arange(len(event)), index=event.index)
    last = idx.where(event).groupby(groups).ffill()
    first = idx.groupby(groups).transform("min")
    return (idx - last.fillna(first - 120)).clip(upper=120)


def build_features(d: pd.DataFrame) -> pd.DataFrame:
    f = d.copy()
    g = f.groupby("project_id", sort=False)
    pid = f["project_id"]

    elapsed = _months_diff(f["report_month"], f["start_date"]).clip(lower=0)
    planned = _months_diff(f["original_completion"], f["start_date"]).clip(lower=1)
    f["elapsed_months"] = elapsed
    f["planned_months"] = planned
    f["elapsed_frac"] = (elapsed / planned).round(4)
    f["expected_progress"] = (100 * elapsed / planned).clip(upper=100)
    f["completion_gap"] = f["expected_progress"] - f["progress"]

    p = f["progress"]
    f["velocity_3m"] = ((p - g["progress"].shift(3)) / 3).fillna(p / (elapsed + 1))
    f["velocity_6m"] = ((p - g["progress"].shift(6)) / 6).fillna(f["velocity_3m"])
    f["velocity_accel"] = (f["velocity_3m"] - f.groupby("project_id")["velocity_3m"].shift(3)).fillna(0)

    f["cost_growth_pct"] = (f["revised_cost_cr"] / f["original_cost_cr"] - 1) * 100
    cost_rev = (f["revised_cost_cr"] > g["revised_cost_cr"].shift(1) * 1.005).fillna(False)
    f["n_cost_revisions"] = cost_rev.groupby(pid).cumsum()
    f["months_since_cost_revision"] = _since_last_event(cost_rev, pid)

    f["slip_months"] = _months_diff(f["revised_completion"], f["original_completion"]).clip(lower=0)
    sched_rev = (f["revised_completion"] > g["revised_completion"].shift(1)).fillna(False)
    f["n_schedule_revisions"] = sched_rev.groupby(pid).cumsum()
    f["months_since_schedule_revision"] = _since_last_event(sched_rev, pid)
    f["months_left"] = _months_diff(f["revised_completion"], f["report_month"])
    required = (100 - p) / f["months_left"].clip(lower=1)
    f["required_velocity"] = required
    f["velocity_ratio"] = (f["velocity_3m"] / required.replace(0, np.nan)).clip(0, 3).fillna(1.0)

    f["expenditure_ratio"] = (f["expenditure"] / f["revised_cost_cr"] * 100).clip(0, 150)
    f["spend_progress_gap"] = f["expenditure_ratio"] - p
    f["log_original_cost"] = np.log10(f["original_cost_cr"])

    bn = f["bottleneck"]
    active = ~bn.isin(["none", "unknown"])
    f["bottleneck_active"] = active.astype(int)
    streak_break = (~active).groupby(pid).cumsum()
    f["bottleneck_streak"] = active.groupby([pid, streak_break]).cumsum().astype(int)
    f["bottleneck_months_6m"] = active.astype(int).groupby(pid).transform(lambda s: s.rolling(6, min_periods=1).sum())
    for col, cats in _BN_GROUPS.items():
        f[col] = bn.isin(cats).astype(int).groupby(pid).transform(lambda s: s.rolling(6, min_periods=1).sum())
    reported = (~(f["flag_missing_progress"] | f["flag_missing_expenditure"] | f["flag_missing_remarks"])).astype(float)
    f["report_quality_6m"] = reported.groupby(pid).transform(lambda s: s.rolling(6, min_periods=1).mean())

    _peer_context(f)
    f[ALL_FEATURES] = f[ALL_FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
    return add_labels(f)


def _peer_context(f: pd.DataFrame) -> None:
    """Leave-one-out peer averages at the same reporting month (no look-ahead, excludes the project itself).
    These are not CUF fields of the project but can be derived from the rest of the portfolio."""
    for col, key, val in (("peer_agency_slip", "implementing_agency", "slip_months"),
                          ("peer_agency_cost_growth", "implementing_agency", "cost_growth_pct"),
                          ("peer_state_slip", "state", "slip_months"),
                          ("peer_sector_cost_growth", "sector", "cost_growth_pct")):
        if key not in f.columns:
            f[col] = np.nan
            continue
        g = f.groupby([f[key].astype("string").fillna("?"), "report_month"])[val]
        tot, n = g.transform("sum"), g.transform("count")
        f[col] = ((tot - f[val].fillna(0)) / (n - f[val].notna().astype(int))).where(n > 1)


def add_labels(f: pd.DataFrame) -> pd.DataFrame:
    # a month counts as observed only if the project actually reported it; carried-forward gap
    # months would otherwise look like stalls and teach the models a reporting artefact
    f["reported"] = f["physical_progress_pct"].notna() | f["cumulative_expenditure_cr"].notna()
    g = f.groupby("project_id", sort=False)
    completed = g["status"].transform("last").eq("Completed")
    n_rows = g["progress"].transform("size")
    pos = g.cumcount()
    ongoing_now = f["progress"] < 99.5

    for h in HORIZONS:
        observed = (pos + h < n_rows)
        # a project that completed inside the window is observable: its future is its final state
        within_after_completion = completed & ~observed
        fut_cost = g["cost_growth_pct"].shift(-h).fillna(g["cost_growth_pct"].transform("last"))
        fut_slip = g["slip_months"].shift(-h).fillna(g["slip_months"].transform("last"))
        fut_prog = g["progress"].shift(-h).fillna(g["progress"].transform("last"))
        reported_then = g["reported"].shift(-h).fillna(False).astype(bool)
        known = ((observed & reported_then) | within_after_completion) & ongoing_now & f["reported"]

        cost_evt = (fut_cost - f["cost_growth_pct"]) >= COST_EVENT_PP
        sched_evt = (fut_slip - f["slip_months"]) >= SCHEDULE_EVENT_MONTHS
        # stall = far below the project's own planned pace (overdue projects are not penalised
        # for the impossible catch-up velocity their revised date would imply)
        need = np.minimum(100 / f["planned_months"] * h, 100 - f["progress"])
        stall_evt = ((fut_prog - f["progress"]) < STALL_RATIO * need) & (fut_prog < 99.5)
        mobilising = f["elapsed_months"] < 4  # slow start-up months are normal, not a stall

        f[f"y_cost_{h}"] = cost_evt.astype(float).where(known)
        f[f"y_schedule_{h}"] = sched_evt.astype(float).where(known)
        f[f"y_implementation_{h}"] = stall_evt.astype(float).where(known & ~mobilising)
    # final outcomes (for cost/time overrun regression, completed projects only)
    f["final_cost_growth_pct"] = g["cost_growth_pct"].transform("last").where(completed)
    f["final_slip_months"] = g["slip_months"].transform("last").where(completed)
    return f
