"""Data Trust engine -- runs *before* any risk prediction.

Detects missing, stale, contradictory and anomalous CUF values, produces a
cleaned panel for downstream engines, and a 0-100 data-confidence score per
project so every risk score is shown next to how much the data behind it can be
trusted.

Row-level checks
  * missing progress / expenditure / remarks
  * expenditure exceeding the sanctioned (revised) cost
  * physical progress regressing (cumulative progress cannot fall)
  * implausible spikes (e.g. 4.5 -> 45 -> 5.1)
  * multivariate anomalies via IsolationForest on month-on-month deltas
Project-level
  * staleness: months since the last report vs the portfolio reporting month
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from prism.config import settings

ISSUE_LABELS = {
    "missing_progress": "Physical progress not reported",
    "missing_expenditure": "Expenditure not reported",
    "missing_remarks": "Remarks not reported",
    "exp_exceeds_cost": "Cumulative expenditure exceeds sanctioned cost",
    "progress_regression": "Cumulative physical progress decreased",
    "progress_spike": "Implausible one-month progress spike",
    "anomaly": "Statistical anomaly in monthly movement (IsolationForest)",
}


def clean_and_flag(df: pd.DataFrame) -> pd.DataFrame:
    """Adds ``flag_*`` columns plus cleaned ``progress`` and ``expenditure``."""
    d = df.copy()
    g = d.groupby("project_id", sort=False)
    prog, exp = d["physical_progress_pct"], d["cumulative_expenditure_cr"]

    d["flag_missing_progress"] = prog.isna()
    d["flag_missing_expenditure"] = exp.isna()
    # sources without any remarks field (e.g. Flash Report tables) are not penalised for it
    d["flag_missing_remarks"] = d["remarks"].isna() if d["remarks"].notna().any() else False
    d["flag_exp_exceeds_cost"] = exp > d["revised_cost_cr"] * 1.02

    prev = g["physical_progress_pct"].shift(1)
    nxt = g["physical_progress_pct"].shift(-1)
    prev_ff = g["physical_progress_pct"].transform(lambda s: s.ffill().shift(1))
    # spike: jumps far above both neighbours
    d["flag_progress_spike"] = (prog - prev > 20) & (prog - nxt > 15)
    running_max = g["physical_progress_pct"].transform(lambda s: s.where(~d.loc[s.index, "flag_progress_spike"]).cummax().shift(1))
    d["flag_progress_regression"] = (prog < running_max - 1.0) & ~d["flag_progress_spike"]

    # cleaned series: drop flagged values, forward-fill, enforce monotonicity
    p_clean = prog.mask(d["flag_progress_spike"] | d["flag_progress_regression"])
    d["progress"] = p_clean.groupby(d["project_id"]).transform(lambda s: s.ffill().fillna(0).cummax()).clip(0, 100)
    e_clean = exp.mask(d["flag_exp_exceeds_cost"])
    d["expenditure"] = e_clean.groupby(d["project_id"]).transform(lambda s: s.ffill().fillna(0).cummax())

    # multivariate anomaly detection on month-on-month movement of the raw series
    raw_dp = (prog - prev_ff).fillna(0)
    raw_de = (exp - g["cumulative_expenditure_cr"].transform(lambda s: s.ffill().shift(1))).fillna(0)
    feats = pd.DataFrame({
        "dp": raw_dp,
        "de_ratio": (raw_de / d["revised_cost_cr"] * 100).fillna(0),
        "spend_gap": (d["expenditure"] / d["revised_cost_cr"] * 100 - d["progress"]).fillna(0),
        "dcost": (d["revised_cost_cr"] / g["revised_cost_cr"].shift(1) - 1).fillna(0) * 100,
    }).replace([np.inf, -np.inf], 0)
    iso = IsolationForest(n_estimators=150, contamination=0.012, random_state=settings.random_seed)
    d["anomaly_score"] = -iso.fit(feats).score_samples(feats)
    d["flag_anomaly"] = iso.predict(feats) == -1
    return d


def project_trust(d: pd.DataFrame) -> pd.DataFrame:
    """Project-level data-confidence score (0-100) and its components."""
    current = d["report_month"].max()
    flag_cols = [c for c in d.columns if c.startswith("flag_")]
    g = d.groupby("project_id", sort=False)
    last = g.tail(1).set_index("project_id")
    agg = g[flag_cols].mean()
    recent = d[d["report_month"] > current - pd.DateOffset(months=12)].groupby("project_id")[flag_cols].sum()

    out = pd.DataFrame(index=agg.index)
    out["missingness_pct"] = (agg[["flag_missing_progress", "flag_missing_expenditure", "flag_missing_remarks"]].mean(axis=1) * 100).round(1)
    months_since = ((current.year - last["report_month"].dt.year) * 12 + (current.month - last["report_month"].dt.month))
    ongoing = last["status"].eq("Ongoing")
    out["staleness_months"] = np.where(ongoing, months_since, 0).astype(int)
    out["n_contradictions"] = g[["flag_exp_exceeds_cost", "flag_progress_regression", "flag_progress_spike"]].sum().sum(axis=1).astype(int)
    out["n_anomalies"] = g["flag_anomaly"].sum().astype(int)
    out["recent_issues"] = recent.reindex(out.index).fillna(0).sum(axis=1).astype(int)

    completeness = 100 - out["missingness_pct"] * 2.5
    freshness = np.clip(100 - out["staleness_months"] * 18, 0, 100)
    consistency = np.clip(100 - 400 * g[["flag_exp_exceeds_cost", "flag_progress_regression", "flag_progress_spike"]].mean().sum(axis=1), 0, 100)
    stability = np.clip(100 - 600 * agg["flag_anomaly"], 0, 100)
    out["completeness_score"] = completeness.clip(0, 100).round(1)
    out["freshness_score"] = pd.Series(freshness, index=out.index).round(1)
    out["consistency_score"] = consistency.round(1)
    out["stability_score"] = stability.round(1)
    out["data_confidence"] = (0.3 * out["completeness_score"] + 0.3 * out["freshness_score"]
                              + 0.25 * out["consistency_score"] + 0.15 * out["stability_score"]).round(1)
    out["confidence_grade"] = pd.cut(out["data_confidence"], [-1, 60, 80, 101], labels=["Low", "Medium", "High"]).astype(str)
    out["last_report_month"] = last["report_month"].dt.strftime("%Y-%m")
    return out.reset_index()


def issue_log(d: pd.DataFrame, project_id: str | None = None, limit: int = 200) -> list[dict]:
    """Flat list of detected data issues (most recent first) for the UI."""
    sub = d if project_id is None else d[d["project_id"] == project_id]
    rows = []
    for key, label in ISSUE_LABELS.items():
        col = f"flag_{key}"
        hit = sub[sub[col]]
        for r in hit[["project_id", "report_month", "physical_progress_pct", "cumulative_expenditure_cr", "revised_cost_cr"]].itertuples(index=False):
            rows.append(dict(project_id=r.project_id, month=r.report_month.strftime("%Y-%m"), issue=key, label=label,
                             reported_progress=None if pd.isna(r.physical_progress_pct) else float(r.physical_progress_pct),
                             reported_expenditure=None if pd.isna(r.cumulative_expenditure_cr) else float(r.cumulative_expenditure_cr),
                             revised_cost=float(r.revised_cost_cr)))
    rows.sort(key=lambda r: r["month"], reverse=True)
    return rows[:limit]
