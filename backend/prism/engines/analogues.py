"""Historical analogue engine.

"Projects like this one, at the same stage of life, went on to..." -- for an
ongoing project we search completed OCMS/PAIMANA projects for the snapshot that
most resembles the project *today* (same stage, cost growth, slippage, pace,
bottleneck load) and report what eventually happened to them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANALOGUE_FEATURES = ["elapsed_frac", "progress", "completion_gap", "cost_growth_pct", "slip_months",
                     "velocity_6m", "bottleneck_months_6m", "log_original_cost"]
WEIGHTS = np.array([1.5, 1.5, 1.0, 1.2, 1.2, 0.8, 0.8, 0.6])


class AnalogueIndex:
    def __init__(self, features: pd.DataFrame):
        pool = features[features["final_cost_growth_pct"].notna() & (features["progress"] < 99.5)]
        self.pool = pool[["project_id", "project_name", "sector", "ministry", "state", "report_month",
                          "final_cost_growth_pct", "final_slip_months", *ANALOGUE_FEATURES]].reset_index(drop=True)
        X = self.pool[ANALOGUE_FEATURES].fillna(0).to_numpy(float)
        self.mu, self.sd = X.mean(axis=0), X.std(axis=0) + 1e-9
        self.X = (X - self.mu) / self.sd

    def query(self, row: pd.Series, k: int = 5) -> list[dict]:
        x = (row[ANALOGUE_FEATURES].fillna(0).to_numpy(float) - self.mu) / self.sd
        dist = np.sqrt((((self.X - x) ** 2) * WEIGHTS).sum(axis=1))
        dist = dist + np.where(self.pool["sector"].to_numpy() == row["sector"], 0.0, 0.75)  # prefer same sector
        mask = self.pool["project_id"].to_numpy() != row["project_id"]
        cand = self.pool.assign(distance=dist)[mask].sort_values("distance")
        best = cand.drop_duplicates("project_id").head(k)
        return [{
            "project_id": r.project_id, "project_name": r.project_name, "sector": r.sector, "ministry": r.ministry,
            "state": r.state, "matched_month": r.report_month.strftime("%Y-%m"),
            "similarity": round(float(1 / (1 + r.distance)), 3),
            "progress_then": round(float(r.progress), 1), "cost_growth_then": round(float(r.cost_growth_pct), 1),
            "slip_then": int(r.slip_months),
            "final_cost_growth_pct": round(float(r.final_cost_growth_pct), 1),
            "final_slip_months": int(r.final_slip_months),
        } for r in best.itertuples(index=False)]


def summarise(analogues: list[dict]) -> dict:
    if not analogues:
        return {}
    cg = np.array([a["final_cost_growth_pct"] for a in analogues])
    sl = np.array([a["final_slip_months"] for a in analogues])
    return {"n": len(analogues), "median_final_cost_growth_pct": round(float(np.median(cg)), 1),
            "median_final_slip_months": round(float(np.median(sl)), 1),
            "share_cost_growth_over_20pct": round(float((cg > 20).mean() * 100), 1),
            "share_slip_over_12m": round(float((sl > 12).mean() * 100), 1)}
