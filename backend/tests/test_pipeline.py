import numpy as np
import pandas as pd

from prism.config import DIMENSIONS, HORIZONS
from prism.engines.canonical import build_canonical, load_raw
from prism.engines.features import ALL_FEATURES, build_features
from prism.engines.remarks import classify_remark
from prism.engines.trust import clean_and_flag


def test_generator_matches_cuf_schema(raw_dir):
    raw = load_raw(raw_dir)
    assert raw["master"]["project_id"].is_unique
    assert {"physical_progress_pct", "cumulative_expenditure_cr", "revised_cost_cr", "remarks"} <= set(raw["monthly"].columns)
    assert len(raw["interventions"]) > 0


def test_remark_classifier():
    assert classify_remark("Stage-II forest clearance awaited from MoEF&CC.") == "forest_clearance"
    assert classify_remark("Right-of-Way handover by State Government delayed") == "land_acquisition"
    assert classify_remark("Work progressing as per schedule.") == "none"
    assert classify_remark(float("nan")) == "unknown"


def test_trust_engine_flags_and_cleans(raw_dir):
    d = clean_and_flag(build_canonical(load_raw(raw_dir)))
    assert d["flag_exp_exceeds_cost"].any() and d["flag_progress_regression"].any()
    # cleaned cumulative progress is monotone within every project
    assert (d.groupby("project_id")["progress"].diff().fillna(0) >= -1e-9).all()
    assert (d.loc[d["flag_exp_exceeds_cost"], "expenditure"] <= d.loc[d["flag_exp_exceeds_cost"], "revised_cost_cr"] * 1.02).all()


def test_features_are_point_in_time(raw_dir):
    """Features for month t must not change when data after t is removed (no look-ahead leakage)."""
    c = build_canonical(load_raw(raw_dir))
    full = build_features(clean_and_flag(c))
    pid = full.groupby("project_id").size().idxmax()
    cut = full[full["project_id"] == pid]["report_month"].iloc[20]
    trunc = build_features(clean_and_flag(c[c["report_month"] <= cut]))
    a = full[(full["project_id"] == pid) & (full["report_month"] == cut)][ALL_FEATURES].iloc[0]
    b = trunc[(trunc["project_id"] == pid) & (trunc["report_month"] == cut)][ALL_FEATURES].iloc[0]
    # anomaly flags are fitted on the whole panel, everything else must match exactly
    pd.testing.assert_series_equal(a.drop("report_quality_6m"), b.drop("report_quality_6m"), check_names=False, atol=1e-9)


def test_labels_censored_at_end(state):
    last = state.panel.groupby("project_id").tail(1)
    live_last = last[last["status"] == "Ongoing"]
    assert live_last["y_cost_12"].isna().all()


def test_models_and_outputs(state):
    s = state.suite
    assert set(s.models) == {(d, h) for d in DIMENSIONS for h in HORIZONS}
    xgb = [b for b in s.benchmark if b["model"] == "XGBoost"]
    # discrimination must beat chance wherever the test split has enough events to measure it
    assert all(0.5 < b["auc"] <= 1 for b in xgb if b["base_rate"] * b["n_test"] >= 30)
    assert len(s.cuf_sufficiency) == 9 and len(s.significance) == 9
    L = state.latest
    assert set(L["rag"]) <= {"Red", "Amber", "Green", "Completed"}
    assert L["risk_composite"].between(0, 100).all()
    live = L[L["status"] == "Ongoing"]
    assert (live["cost_q10"] <= live["cost_q50"]).all() and (live["cost_q50"] <= live["cost_q90"]).all()
    assert np.isfinite(L["priority_index"]).all()
