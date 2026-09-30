"""What-if analysis: re-score a project with specific risk drivers neutralised.

The production models are re-run on edited copies of the project's current
features. This shows how sensitive the *model's* warning is to each driver; it
is not a causal estimate of what an administrative action would achieve.
"""
from __future__ import annotations

import pandas as pd

from prism.config import DIMENSIONS, HORIZONS

DISCLAIMER = ("Model sensitivity analysis, not a causal estimate: each scenario re-scores the project with the "
              "named driver neutralised to show how much of the current warning it accounts for.")

BN_COLS = ["bn_land_6m", "bn_clearance_6m", "bn_contractor_6m", "bn_funding_6m", "bn_litigation_6m", "bn_design_geo_6m"]


def _resolve_bottlenecks(x):
    x["bottleneck_active"] = 0
    x["bottleneck_streak"] = 0
    x["bottleneck_months_6m"] = 0
    for c in BN_COLS:
        x[c] = 0
    return x


def _restore_pace(x):
    target = max(float(x["required_velocity"]), float(x["velocity_6m"]), 0.5)
    x["velocity_3m"] = x["velocity_6m"] = target
    x["velocity_ratio"] = max(float(x["velocity_ratio"]), 1.0)
    x["velocity_accel"] = max(float(x["velocity_accel"]), 0.0)
    return x


def _unblock_funds(x):
    x["bn_funding_6m"] = 0
    x["spend_progress_gap"] = min(float(x["spend_progress_gap"]), 0.0)
    return x


def _strengthen_contractor(x):
    x["bn_contractor_6m"] = 0
    x["contractor_credit_score"] = max(float(x["contractor_credit_score"]), 80.0)
    return x


SCENARIOS = {
    "resolve_bottlenecks": ("All reported bottlenecks resolved", _resolve_bottlenecks),
    "restore_pace": ("Execution pace restored to required velocity", _restore_pace),
    "unblock_funds": ("Funding / cash-flow constraint removed", _unblock_funds),
    "strengthen_contractor": ("Contractor capacity strengthened", _strengthen_contractor),
    "combined": ("Combined: bottlenecks resolved + pace restored",
                 lambda x: _restore_pace(_resolve_bottlenecks(x))),
}


def run(suite, row: pd.Series) -> dict:
    base = suite.predict(row.to_frame().T)
    results = [{"key": "current", "label": "Current trajectory (do nothing)",
                **_summ(base.iloc[0])}]
    for key, (label, fn) in SCENARIOS.items():
        x = fn(row.copy())
        s = suite.predict(x.to_frame().T)
        r = {"key": key, "label": label, **_summ(s.iloc[0])}
        r["delta_composite"] = round(r["risk_composite"] - results[0]["risk_composite"], 2)
        results.append(r)
    return {"disclaimer": DISCLAIMER, "scenarios": results}


def _summ(s: pd.Series) -> dict:
    return {"risk_composite": round(float(s["risk_composite"]), 2),
            **{f"risk_{d}": round(float(s[f"risk_{d}"]), 2) for d in DIMENSIONS},
            "probabilities": {f"{d}_{h}": round(float(s[f"p_{d}_{h}"]), 4) for d in DIMENSIONS for h in HORIZONS}}
