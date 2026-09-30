"""Forecast engine (statsmodels).

Per-project physical-progress and expenditure paths are forecast with a damped
Holt (additive-trend exponential smoothing) model; an ARIMA(1,1,0) with drift
is fitted as a challenger and the lower-AIC model is kept. Prediction intervals
come from the model's residual variance growing with the horizon. From the
progress path we derive a projected completion month and compare it to the
currently reported revised completion.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")
Z80 = 1.2816


def _fit_series(y: np.ndarray, horizon: int) -> dict:
    n = len(y)
    if n < 6 or np.allclose(y, y[0]):
        slope = (y[-1] - y[0]) / max(n - 1, 1) if n > 1 else 0.0
        mean = y[-1] + slope * np.arange(1, horizon + 1)
        return {"method": "linear trend (short history)", "mean": mean, "sd": np.full(horizon, max(abs(slope), 0.5)) * np.sqrt(np.arange(1, horizon + 1))}
    best = None
    try:
        es = ExponentialSmoothing(y, trend="add", damped_trend=True, initialization_method="estimated").fit()
        resid = np.std(es.resid[1:]) if n > 2 else 1.0
        best = {"method": "Holt damped-trend exponential smoothing", "aic": es.aic, "mean": es.forecast(horizon),
                "sd": resid * np.sqrt(np.arange(1, horizon + 1))}
    except Exception:
        pass
    try:
        ar = ARIMA(y, order=(1, 1, 0), trend="t").fit()
        fc = ar.get_forecast(horizon)
        cand = {"method": "ARIMA(1,1,0) with drift", "aic": ar.aic, "mean": fc.predicted_mean,
                "sd": np.sqrt(np.maximum(fc.var_pred_mean, 1e-9))}
        if best is None or cand["aic"] < best["aic"]:
            best = cand
    except Exception:
        pass
    if best is None:
        return _fit_series(y[-3:], horizon)
    return best


def forecast_project(group: pd.DataFrame, horizon: int = 12) -> dict:
    g = group.sort_values("report_month").tail(48)
    last_month = g["report_month"].iloc[-1]
    months = [(last_month + pd.DateOffset(months=i)).strftime("%Y-%m") for i in range(1, horizon + 1)]
    out = {"months": months}

    prog = g["progress"].to_numpy(float)
    pf = _fit_series(prog, horizon)
    mean = np.clip(np.maximum.accumulate(np.maximum(pf["mean"], prog[-1])), 0, 100)
    out["progress"] = {"method": pf["method"], "mean": mean.round(2).tolist(),
                       "lower": np.clip(mean - Z80 * pf["sd"], prog[-1], 100).round(2).tolist(),
                       "upper": np.clip(mean + Z80 * pf["sd"], prog[-1], 100).round(2).tolist()}

    exp = g["expenditure"].to_numpy(float)
    ef = _fit_series(exp, horizon)
    emean = np.maximum.accumulate(np.maximum(ef["mean"], exp[-1]))
    out["expenditure"] = {"method": ef["method"], "mean": emean.round(2).tolist(),
                          "lower": np.maximum(emean - Z80 * ef["sd"], exp[-1]).round(2).tolist(),
                          "upper": (emean + Z80 * ef["sd"]).round(2).tolist()}

    # projected completion from recent realised velocity (robust to the forecast's damping)
    vel = float(g["velocity_6m"].iloc[-1]) if "velocity_6m" in g else 0.0
    remaining = 100 - prog[-1]
    if remaining <= 0.5:
        proj = last_month
    elif vel > 0.05:
        proj = last_month + pd.DateOffset(months=int(np.ceil(remaining / vel)))
    else:
        proj = None
    revised = g["revised_completion"].iloc[-1]
    out["projected_completion"] = proj.strftime("%Y-%m") if proj is not None else None
    out["revised_completion"] = revised.strftime("%Y-%m")
    out["additional_slip_months"] = (int((proj.year - revised.year) * 12 + proj.month - revised.month)
                                     if proj is not None else None)
    out["velocity_pp_per_month"] = round(vel, 3)
    return out
