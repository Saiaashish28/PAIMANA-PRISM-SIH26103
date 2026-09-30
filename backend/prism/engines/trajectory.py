"""Risk Trajectory engine + Early Warning engine.

Static risk says *how risky* a project is; trajectory says *where it is heading*.
For every project-month we have the composite risk score (0-100). We compute

  risk velocity      slope of composite risk over the trailing 6 months (points / month)
  risk acceleration  change in velocity versus 3 months earlier

and classify the trajectory. Early warnings are raised per dimension at the
shortest horizon (3 -> 6 -> 12 months) whose calibrated probability crosses the
alert threshold chosen on held-out projects, plus velocity-drop anomaly alerts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from prism.config import DIMENSIONS, HORIZONS, RAG_AMBER, RAG_RED

TRAJECTORY_ORDER = ["Rapidly Deteriorating", "Deteriorating", "Stable", "Improving"]
SEVERITY = {3: "Critical", 6: "High", 12: "Watch"}
DIM_LABEL = {"cost": "Cost overrun", "schedule": "Schedule slippage", "implementation": "Implementation stall"}


def _slope(v: np.ndarray) -> float:
    x = np.arange(len(v), dtype=float)
    x -= x.mean()
    return float(np.dot(v - v.mean(), x) / np.dot(x, x))


def _rolling_slope(y: pd.Series, window: int = 6) -> pd.Series:
    return y.rolling(window, min_periods=3).apply(_slope, raw=True)


def add_trajectory(panel: pd.DataFrame) -> pd.DataFrame:
    """``panel`` holds project_id + risk_* columns in chronological order per project."""
    p = panel.copy()
    # light smoothing so a single noisy month does not read as a trend
    smooth = p.groupby("project_id", sort=False)["risk_composite"].transform(lambda s: s.ewm(span=3).mean())
    p["risk_velocity"] = smooth.groupby(p["project_id"], sort=False).transform(_rolling_slope).fillna(0.0)
    p["risk_acceleration"] = (p["risk_velocity"] - p.groupby("project_id", sort=False)["risk_velocity"].shift(3)).fillna(0.0)
    for dim in DIMENSIONS:
        p[f"velocity_{dim}"] = p.groupby("project_id", sort=False)[f"risk_{dim}"].transform(_rolling_slope).fillna(0.0)
    p["trajectory"] = classify(p["risk_velocity"], p["risk_acceleration"])
    return p


def classify(velocity: pd.Series, accel: pd.Series) -> pd.Series:
    return pd.Series(np.select(
        [(velocity >= 4.0) | ((velocity >= 2.5) & (accel >= 1.5)), velocity >= 1.5, velocity <= -1.5],
        ["Rapidly Deteriorating", "Deteriorating", "Improving"], default="Stable"), index=velocity.index)


def early_warnings(latest: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """One row per (project, dimension) with an active warning at the latest month."""
    rows = []
    live = latest[latest["status"] == "Ongoing"]
    for r in live.itertuples(index=False):
        rd = r._asdict()
        for dim in DIMENSIONS:
            for h in HORIZONS:
                prob, thr = rd[f"p_{dim}_{h}"], thresholds[(dim, h)]
                if prob >= thr:
                    sev = SEVERITY[h]
                    # physical progress is reported in lumps, so a short-horizon stall signal is only
                    # Critical when the 6-month model agrees (a sustained stall, not one flat quarter)
                    if dim == "implementation" and h == 3 and rd["p_implementation_6"] < thresholds[(dim, 6)]:
                        sev = "High"
                    rows.append(dict(project_id=r.project_id, dimension=dim, warning=DIM_LABEL[dim], horizon_months=h,
                                     severity=sev, probability=round(float(prob), 4), threshold=round(float(thr), 4),
                                     trajectory=r.trajectory, risk_velocity=round(float(r.risk_velocity), 2), source="model"))
                    break
        # anomaly: milestone velocity collapses versus the project's own recent pace
        if (rd["velocity_6m"] > 0.6 and rd["velocity_3m"] < 0.35 * rd["velocity_6m"] and rd["progress"] < 95):
            rows.append(dict(project_id=r.project_id, dimension="implementation", warning="Milestone velocity drop",
                             horizon_months=3, severity="High", probability=None, threshold=None,
                             trajectory=r.trajectory, risk_velocity=round(float(r.risk_velocity), 2), source="anomaly"))
    return pd.DataFrame(rows, columns=["project_id", "dimension", "warning", "horizon_months", "severity", "probability",
                                       "threshold", "trajectory", "risk_velocity", "source"])


def rag_bands(panel: pd.DataFrame) -> dict[str, float]:
    """Composite-risk bands calibrated on history: Red = top 15%, Amber = top 40% of all past
    ongoing project-months (never below the fixed floors). Because the reference is history,
    a portfolio that deteriorates shows more Reds rather than a constant share."""
    hist = panel.loc[panel["status"] == "Ongoing", "risk_composite"].dropna()
    if len(hist) < 100:
        return {"red": RAG_RED, "amber": RAG_AMBER, "method": "fixed"}
    return {"red": round(max(float(hist.quantile(0.85)), RAG_AMBER + 5), 2),
            "amber": round(max(float(hist.quantile(0.60)), RAG_AMBER / 2), 2), "method": "historical quantiles (85th / 60th)"}


def rag_status(latest: pd.DataFrame, warnings: pd.DataFrame, bands: dict | None = None) -> pd.Series:
    """Red: Critical (3-month) warnings in two or more dimensions, a Critical warning on a deteriorating
    project, or composite risk in the red band. Amber: a Critical or velocity-anomaly warning, or
    composite risk in the amber band (6/12-month warnings alone keep a project on the watch list).
    Closed projects keep their status (Completed / Dropped)."""
    bands = bands or {"red": RAG_RED, "amber": RAG_AMBER}
    w = warnings[(warnings["source"] == "model") & (warnings["severity"] == "Critical")]
    n3 = latest["project_id"].map(w.groupby("project_id").size()).fillna(0)
    deteriorating = latest["trajectory"].isin(["Deteriorating", "Rapidly Deteriorating"])
    red = (n3 >= 2) | ((n3 >= 1) & deteriorating) | (latest["risk_composite"] >= bands["red"])
    anomaly = latest["project_id"].isin(warnings.loc[warnings["source"] == "anomaly", "project_id"])
    amber = (n3 >= 1) | anomaly | (latest["risk_composite"] >= bands["amber"])
    closed = latest["status"] != "Ongoing"
    out = np.select([closed, red, amber], [latest["status"], "Red", "Amber"], default="Green")
    return pd.Series(out, index=latest.index)
