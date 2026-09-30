"""Explainability: SHAP (TreeExplainer) local drivers for every project and model."""
from __future__ import annotations

import numpy as np
import pandas as pd
import shap

from prism.config import DIMENSIONS, HORIZONS
from prism.engines.features import ALL_FEATURES, FEATURE_LABELS, NON_CUF_FEATURES


def shap_for_latest(suite, latest: pd.DataFrame) -> dict[tuple[str, int], np.ndarray]:
    """SHAP values (log-odds contributions) for the latest row of each project, per model."""
    X = latest[ALL_FEATURES]
    out = {}
    for dim in DIMENSIONS:
        for h in HORIZONS:
            explainer = shap.TreeExplainer(suite.models[(dim, h)])
            out[(dim, h)] = np.asarray(explainer.shap_values(X))
    return out


def drivers(shap_row: np.ndarray, x_row: pd.Series, top_n: int = 6) -> list[dict]:
    order = np.argsort(-np.abs(shap_row))[:top_n]
    return [{
        "feature": ALL_FEATURES[i], "label": FEATURE_LABELS[ALL_FEATURES[i]],
        "value": None if pd.isna(x_row[ALL_FEATURES[i]]) else round(float(x_row[ALL_FEATURES[i]]), 3),
        "shap": round(float(shap_row[i]), 4),
        "direction": "raises risk" if shap_row[i] > 0 else "lowers risk",
        "non_cuf": ALL_FEATURES[i] in NON_CUF_FEATURES,
    } for i in order]


def global_shap(shap_values: dict) -> dict[str, list[dict]]:
    res = {}
    for (dim, h), vals in shap_values.items():
        mean_abs = np.abs(vals).mean(axis=0)
        tot = mean_abs.sum() or 1.0
        res[f"{dim}_{h}"] = sorted([{"feature": f, "label": FEATURE_LABELS[f], "mean_abs_shap": round(float(v), 4),
                                     "share_pct": round(float(100 * v / tot), 2), "non_cuf": f in NON_CUF_FEATURES}
                                    for f, v in zip(ALL_FEATURES, mean_abs)], key=lambda r: -r["mean_abs_shap"])
    return res
