"""Risk engine: early-warning classifiers, overrun regressors and the ML-vs-statistics benchmark.

For every (dimension, horizon) pair we train:
  * XGBoost                     -- production model
  * HistGradientBoosting        -- ML challenger
  * Logistic regression         -- conventional statistical baseline

Projects (not rows) are split 60 / 15 / 25 into train / calibration / test so no
project leaks across splits. Alert thresholds are chosen on the calibration
split, metrics are reported on the untouched test split, and significance of the
ML gain is assessed with a project-clustered bootstrap. Production models are
then refit on every labelled row with the same hyper-parameters.

Also here: CUF sufficiency (CUF-only vs CUF + non-CUF), warning lead-time
analysis, and quantile regressors for final cost growth / time overrun.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, fbeta_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from prism.config import DIMENSIONS, HORIZONS, settings
from prism.engines.features import ALL_FEATURES, CUF_FEATURES, FEATURE_LABELS, NON_CUF_FEATURES

warnings.filterwarnings("ignore", category=UserWarning)

N_BOOT = 200
QUANTILES = (0.1, 0.5, 0.9)


def _xgb(seed: int) -> XGBClassifier:
    return XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.85,
                         colsample_bytree=0.8, min_child_weight=3, reg_lambda=1.0, tree_method="hist",
                         eval_metric="logloss", n_jobs=4, random_state=seed)


def _hgb(seed: int) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=24,
                                          l2_regularization=0.5, random_state=seed)


def _logit():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=3000))


def split_projects(project_ids: np.ndarray, seed: int) -> dict[str, set]:
    rng = np.random.default_rng(seed)
    ids = np.array(sorted(set(project_ids)))
    rng.shuffle(ids)
    n = len(ids)
    a, b = int(n * 0.60), int(n * 0.75)
    return {"train": set(ids[:a]), "calib": set(ids[a:b]), "test": set(ids[b:])}


# Alert policy per horizon: urgent 3-month (Critical) alerts must be precise enough to act on,
# so their threshold favours precision; 6- and 12-month alerts balance precision and recall.
ALERT_BETA = {3: 0.7, 6: 1.0, 12: 1.0}


def _best_threshold(y: np.ndarray, p: np.ndarray, beta: float = 1.0) -> float:
    """F-beta optimal alert threshold (beta < 1 favours precision, beta > 1 favours recall)."""
    grid = np.unique(np.quantile(p, np.linspace(0.3, 0.995, 120)))
    scores = [fbeta_score(y, p >= t, beta=beta, zero_division=0) for t in grid]
    return float(grid[int(np.argmax(scores))])


def _cluster_bootstrap(y, p_a, p_b, groups, n_boot=N_BOOT, seed=0) -> dict:
    """AUC(a) - AUC(b) with a project-clustered bootstrap CI and two-sided p-value."""
    rng = np.random.default_rng(seed)
    codes, uniq = pd.factorize(groups)
    idx_by_group = [np.flatnonzero(codes == k) for k in range(len(uniq))]
    diffs = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([idx_by_group[k] for k in pick])
        yy = y[idx]
        if yy.min() == yy.max():
            continue
        diffs.append(roc_auc_score(yy, p_a[idx]) - roc_auc_score(yy, p_b[idx]))
    diffs = np.array(diffs)
    point = roc_auc_score(y, p_a) - roc_auc_score(y, p_b)
    p_val = float(min(1.0, 2 * min((diffs <= 0).mean(), (diffs >= 0).mean()))) if len(diffs) else float("nan")
    return {"auc_diff": round(float(point), 4), "ci_low": round(float(np.quantile(diffs, 0.025)), 4),
            "ci_high": round(float(np.quantile(diffs, 0.975)), 4), "p_value": round(p_val, 4),
            "significant": bool(np.quantile(diffs, 0.025) > 0)}


def _metrics(y, p, thr) -> dict:
    pred = p >= thr
    tp = int((pred & (y == 1)).sum())
    return {
        "auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "threshold": round(thr, 4),
        "precision": round(tp / max(int(pred.sum()), 1), 4),
        "recall": round(tp / max(int((y == 1).sum()), 1), 4),
        "alert_rate": round(float(pred.mean()), 4),
    }


def _early_stage(te: pd.DataFrame, label: str, p_full: np.ndarray, p_cuf: np.ndarray, cutoff: float = 0.35) -> dict:
    """Non-CUF variables are expected to matter most early in a project's life, before CUF
    progress/expenditure fields have revealed how the project is really performing."""
    mask = (te["elapsed_frac"] < cutoff).to_numpy()
    y = te[label].to_numpy(int)[mask]
    if mask.sum() < 50 or y.min() == y.max():
        return {"early_stage_cuf_only_auc": None, "early_stage_full_auc": None, "early_stage_n": int(mask.sum())}
    return {"early_stage_cuf_only_auc": round(float(roc_auc_score(y, p_cuf[mask])), 4),
            "early_stage_full_auc": round(float(roc_auc_score(y, p_full[mask])), 4),
            "early_stage_n": int(mask.sum())}


@dataclass
class RiskSuite:
    seed: int = settings.random_seed
    models: dict = field(default_factory=dict)          # (dim, h) -> production XGB
    thresholds: dict = field(default_factory=dict)      # (dim, h) -> alert threshold
    benchmark: list = field(default_factory=list)
    significance: list = field(default_factory=list)
    cuf_sufficiency: list = field(default_factory=list)
    lead_times: list = field(default_factory=list)
    permutation: dict = field(default_factory=dict)
    global_importance: dict = field(default_factory=dict)
    regressors: dict = field(default_factory=dict)
    regression_metrics: list = field(default_factory=list)
    split: dict = field(default_factory=dict)
    base_rates: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ training
    def fit(self, f: pd.DataFrame) -> "RiskSuite":
        self.split = split_projects(f["project_id"].unique(), self.seed)
        part = f["project_id"].map(lambda p: "train" if p in self.split["train"] else
                                   "calib" if p in self.split["calib"] else "test")
        bench_scores = {}
        for dim in DIMENSIONS:
            for h in HORIZONS:
                label = f"y_{dim}_{h}"
                lab = f[f[label].notna()]
                lpart = part.loc[lab.index]
                tr, ca, te = (lab[lpart == s] for s in ("train", "calib", "test"))
                X_tr, y_tr = tr[ALL_FEATURES], tr[label].to_numpy(int)
                self.base_rates[f"{dim}_{h}"] = round(float(lab[label].mean()), 4)

                algos = {"XGBoost": _xgb(self.seed), "HistGradientBoosting": _hgb(self.seed),
                         "Logistic regression (statistical baseline)": _logit()}
                test_p = {}
                for name, model in algos.items():
                    model.fit(X_tr, y_tr)
                    thr = _best_threshold(ca[label].to_numpy(int), model.predict_proba(ca[ALL_FEATURES])[:, 1],
                                          beta=ALERT_BETA[h])
                    p = model.predict_proba(te[ALL_FEATURES])[:, 1]
                    test_p[name] = p
                    self.benchmark.append({"dimension": dim, "horizon": h, "model": name,
                                           "n_train": len(tr), "n_test": len(te), "base_rate": round(float(te[label].mean()), 4),
                                           **_metrics(te[label].to_numpy(int), p, thr)})
                    if name == "XGBoost":
                        self.thresholds[(dim, h)] = thr
                        bench_scores[(dim, h, "xgb")] = (model, thr)
                    elif name.startswith("Logistic"):
                        bench_scores[(dim, h, "logit")] = (model, thr)
                y_te, grp = te[label].to_numpy(int), te["project_id"].to_numpy()
                self.significance.append({"dimension": dim, "horizon": h,
                                          "comparison": "XGBoost vs logistic regression",
                                          **_cluster_bootstrap(y_te, test_p["XGBoost"],
                                                               test_p["Logistic regression (statistical baseline)"], grp,
                                                               seed=self.seed)})
                # CUF sufficiency: same split, CUF-only vs CUF + non-CUF
                cuf = _xgb(self.seed).fit(tr[CUF_FEATURES], y_tr)
                p_cuf = cuf.predict_proba(te[CUF_FEATURES])[:, 1]
                boot = _cluster_bootstrap(y_te, test_p["XGBoost"], p_cuf, grp, seed=self.seed + 1)
                self.cuf_sufficiency.append({
                    "dimension": dim, "horizon": h,
                    "cuf_only_auc": round(float(roc_auc_score(y_te, p_cuf)), 4),
                    "cuf_plus_noncuf_auc": round(float(roc_auc_score(y_te, test_p["XGBoost"])), 4),
                    "cuf_only_pr_auc": round(float(average_precision_score(y_te, p_cuf)), 4),
                    "cuf_plus_noncuf_pr_auc": round(float(average_precision_score(y_te, test_p["XGBoost"])), 4),
                    "uplift": boot["auc_diff"], "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
                    "p_value": boot["p_value"], "significant": boot["significant"],
                    **_early_stage(te, label, test_p["XGBoost"], p_cuf),
                })
                if h == 6:
                    xgb_model = bench_scores[(dim, h, "xgb")][0]
                    sample = te.sample(min(len(te), 4000), random_state=self.seed)
                    pi = permutation_importance(xgb_model, sample[ALL_FEATURES], sample[label].to_numpy(int),
                                                scoring="roc_auc", n_repeats=4, random_state=self.seed, n_jobs=1)
                    self.permutation[dim] = sorted(
                        [{"feature": c, "label": FEATURE_LABELS[c], "importance": round(float(m), 5),
                          "std": round(float(s), 5), "non_cuf": c in NON_CUF_FEATURES}
                         for c, m, s in zip(ALL_FEATURES, pi.importances_mean, pi.importances_std)],
                        key=lambda r: -r["importance"])

                # production model on all labelled rows
                prod = _xgb(self.seed).fit(lab[ALL_FEATURES], lab[label].to_numpy(int))
                self.models[(dim, h)] = prod
                imp = prod.get_booster().get_score(importance_type="gain")
                tot = sum(imp.values()) or 1.0
                self.global_importance[f"{dim}_{h}"] = sorted(
                    [{"feature": k, "label": FEATURE_LABELS.get(k, k), "gain_pct": round(100 * v / tot, 2)}
                     for k, v in imp.items()], key=lambda r: -r["gain_pct"])

        self._lead_time_analysis(f, part, bench_scores)
        self._fit_regressors(f, part)
        return self

    # ------------------------------------------------------------------ lead time
    def _lead_time_analysis(self, f, part, bench_scores):
        test = f[part == "test"].copy()
        g = test.groupby("project_id", sort=False)
        events = {
            "cost": (test["cost_growth_pct"] - g["cost_growth_pct"].shift(1)) >= 2.0,
            "schedule": (test["slip_months"] - g["slip_months"].shift(1)) >= 3,
        }
        for dim, evt in events.items():
            for key, algo in (("xgb", "XGBoost"), ("logit", "Logistic regression (statistical baseline)")):
                model, thr = bench_scores[(dim, 12, key)]
                alert = pd.Series(model.predict_proba(test[ALL_FEATURES])[:, 1] >= thr, index=test.index)
                leads, detected, n_events = [], 0, 0
                for pid, grp in test.groupby("project_id", sort=False):
                    e_pos = np.flatnonzero(evt.loc[grp.index].to_numpy())
                    a = alert.loc[grp.index].to_numpy()
                    for e in e_pos:
                        if e < 12:
                            continue  # need a full 12-month look-back window
                        n_events += 1
                        window = a[e - 12:e]
                        if window.any():
                            detected += 1
                            leads.append(12 - int(np.argmax(window)))
                quiet = []  # false-alarm rate on windows with no event in the next 12 months
                for pid, grp in test.groupby("project_id", sort=False):
                    ev = evt.loc[grp.index].to_numpy().astype(int)
                    fut = pd.Series(ev[::-1]).rolling(12, min_periods=1).sum().to_numpy()[::-1]
                    fut = np.r_[fut[1:], 0]
                    ok = (fut == 0) & (np.arange(len(ev)) < len(ev) - 12)
                    quiet.extend(alert.loc[grp.index].to_numpy()[ok].tolist())
                self.lead_times.append({
                    "dimension": dim, "model": algo, "n_events": n_events,
                    "detection_rate": round(detected / max(n_events, 1), 4),
                    "median_lead_months": float(np.median(leads)) if leads else None,
                    "mean_lead_months": round(float(np.mean(leads)), 2) if leads else None,
                    "false_alarm_rate": round(float(np.mean(quiet)), 4) if quiet else None,
                })

    # ------------------------------------------------------------------ regression
    def _fit_regressors(self, f, part):
        rows = f[f["final_cost_growth_pct"].notna() & (f["progress"] < 99.5)]
        for target, col, cur in (("final_cost_growth_pct", "cost", "cost_growth_pct"),
                                 ("final_slip_months", "time", "slip_months")):
            tr = rows[part.loc[rows.index] != "test"]
            te = rows[part.loc[rows.index] == "test"]
            preds = {}
            for q in QUANTILES:
                m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=250, learning_rate=0.06,
                                                  max_leaf_nodes=24, random_state=self.seed)
                m.fit(tr[ALL_FEATURES], tr[target])
                preds[q] = np.maximum(m.predict(te[ALL_FEATURES]), te[cur].to_numpy())
                self.regressors[(col, q)] = HistGradientBoostingRegressor(
                    loss="quantile", quantile=q, max_iter=250, learning_rate=0.06, max_leaf_nodes=24,
                    random_state=self.seed).fit(rows[ALL_FEATURES], rows[target])
            ols_cols = [cur, "elapsed_frac", "progress", "completion_gap", "velocity_6m", "log_original_cost"]
            ols = sm.OLS(tr[target], sm.add_constant(tr[ols_cols].fillna(0))).fit()
            ols_pred = np.maximum(ols.predict(sm.add_constant(te[ols_cols].fillna(0), has_constant="add")), te[cur])
            naive = te[cur].to_numpy()
            y = te[target].to_numpy()
            self.regression_metrics.append({
                "target": "Final cost growth (%)" if col == "cost" else "Final time overrun (months)",
                "unit": "%" if col == "cost" else "months",
                "ml_mae": round(float(np.mean(np.abs(preds[0.5] - y))), 3),
                "ols_mae": round(float(np.mean(np.abs(ols_pred - y))), 3),
                "naive_mae": round(float(np.mean(np.abs(naive - y))), 3),
                "interval_coverage_80": round(float(np.mean((y >= preds[0.1]) & (y <= preds[0.9]))), 3),
                "n_test_rows": int(len(te)), "ols_r2_train": round(float(ols.rsquared), 3),
            })

    # ------------------------------------------------------------------ scoring
    def predict(self, f: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=f.index)
        X = f[ALL_FEATURES].astype(float)
        for (dim, h), m in self.models.items():
            out[f"p_{dim}_{h}"] = m.predict_proba(X)[:, 1]
        for dim in DIMENSIONS:
            out[f"risk_{dim}"] = 100 * out[[f"p_{dim}_{h}" for h in HORIZONS]].mean(axis=1)
        out["risk_composite"] = 0.35 * out["risk_cost"] + 0.35 * out["risk_schedule"] + 0.30 * out["risk_implementation"]
        return out

    def predict_overruns(self, f: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=f.index)
        X = f[ALL_FEATURES].astype(float)
        for (col, q), m in self.regressors.items():
            cur = f["cost_growth_pct"] if col == "cost" else f["slip_months"]
            out[f"{col}_q{int(q * 100)}"] = np.maximum(m.predict(X), cur)
        for col in ("cost", "time"):  # keep quantiles ordered
            qs = np.sort(out[[f"{col}_q10", f"{col}_q50", f"{col}_q90"]].to_numpy(), axis=1)
            out[[f"{col}_q10", f"{col}_q50", f"{col}_q90"]] = qs
        return out
