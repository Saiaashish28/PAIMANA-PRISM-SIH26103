"""End-to-end PRISM pipeline.

PAIMANA/OCMS data -> Data Trust -> Features -> Risk models -> Risk trajectory ->
Early warnings & priority -> Explainability -> Portfolio intelligence.

The resulting ``PrismState`` is cached on disk keyed by a fingerprint of the raw
data, so the API starts instantly after the first run and recomputes only when
new monthly data is ingested.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from prism.config import DIMENSIONS, HORIZONS, settings
from prism.engines import portfolio as pf
from prism.engines.analogues import AnalogueIndex
from prism.engines.canonical import build_canonical, load_raw, resolve_source, source_files
from prism.engines.explain import global_shap, shap_for_latest
from prism.engines.features import build_features
from prism.engines.risk_models import RiskSuite
from prism.engines.trajectory import add_trajectory, early_warnings, rag_bands, rag_status
from prism.engines.trust import clean_and_flag, project_trust

log = logging.getLogger("prism.pipeline")
PIPELINE_VERSION = "1.0.0"


@dataclass
class PrismState:
    panel: pd.DataFrame
    latest: pd.DataFrame
    trust: pd.DataFrame
    warnings: pd.DataFrame
    suite: RiskSuite
    shap_latest: dict
    global_shap: dict
    analogues: AnalogueIndex
    portfolio: dict
    historical_interventions: pd.DataFrame
    as_of: pd.Timestamp
    fingerprint: str
    build_seconds: float = 0.0
    meta: dict = field(default_factory=dict)

    def latest_row(self, project_id: str) -> pd.Series:
        hit = self.latest[self.latest["project_id"] == project_id]
        if hit.empty:
            raise KeyError(project_id)
        return hit.iloc[0]

    def history(self, project_id: str) -> pd.DataFrame:
        return self.panel[self.panel["project_id"] == project_id]


def data_fingerprint(raw_dir: Path) -> str:
    h = hashlib.sha1(PIPELINE_VERSION.encode())
    for p in source_files(raw_dir):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


MIN_EVENTS = 15  # per label, so every early-warning model has something to learn from


def check_history(feats: pd.DataFrame) -> None:
    """Fail with a clear message when the data is too short to train early-warning models."""
    problems = []
    for dim in DIMENSIONS:
        for h in HORIZONS:
            y = feats[f"y_{dim}_{h}"].dropna()
            if len(y) == 0 or y.sum() < MIN_EVENTS or (len(y) - y.sum()) < MIN_EVENTS:
                problems.append(f"{dim}/{h}-month ({int(y.sum())} events in {len(y)} labelled project-months)")
    if problems:
        months = feats["report_month"].nunique()
        raise ValueError(
            f"Not enough history to train the early-warning models: the data covers {months} reporting month(s) "
            f"for {feats['project_id'].nunique()} project(s). Each model needs at least {MIN_EVENTS} past events and "
            f"{MIN_EVENTS} non-events whose outcome is already known (12-month warnings need 12+ months of follow-up). "
            f"Add more monthly files (ideally 24+ months). Too thin: " + "; ".join(problems[:4]))


def priority_index(latest: pd.DataFrame, warnings: pd.DataFrame) -> pd.Series:
    """Priority Attention Index (0-100): severity, momentum, financial exposure, urgency."""
    live = latest["status"] == "Ongoing"
    sev = latest["risk_composite"] / max(float(latest.loc[live, "risk_composite"].max()), 1.0)
    mom = (latest["risk_velocity"] / 5).clip(0, 1)
    remaining = (latest["revised_cost_cr"] - latest["expenditure"]).clip(lower=0)
    expo = np.log1p(remaining) / max(float(np.log1p(remaining[live]).max()), 1.0)
    h = latest["project_id"].map(warnings[warnings["source"] == "model"].groupby("project_id")["horizon_months"].min())
    urg = h.map({3: 1.0, 6: 0.6, 12: 0.3}).fillna(0.0)
    pai = 100 * (0.4 * sev + 0.2 * mom + 0.2 * expo + 0.2 * urg)
    return pai.where(live, 0.0).round(1)


def build_state(raw_dir: Path | None = None, source: str = "custom") -> PrismState:
    t0 = time.time()
    raw_dir = Path(raw_dir or resolve_source()[1])
    raw = load_raw(raw_dir)
    log.info("Data trust: cleaning %d monthly snapshots", len(raw["monthly"]))
    cleaned = clean_and_flag(build_canonical(raw))
    trust = project_trust(cleaned)
    feats = build_features(cleaned)
    check_history(feats)

    log.info("Training risk models (3 dimensions x 3 horizons, benchmarked)")
    suite = RiskSuite().fit(feats)
    scores = suite.predict(feats)
    # months without a report keep the last reported risk (no re-scoring of carried-forward values)
    scores = scores.where(feats["reported"]).groupby(feats["project_id"]).ffill().fillna(scores)
    panel = pd.concat([feats, scores], axis=1)
    panel = add_trajectory(panel)

    latest = panel.groupby("project_id", sort=False).tail(1).copy()
    latest = latest.merge(trust, on="project_id", how="left")
    latest = pd.concat([latest.reset_index(drop=True), suite.predict_overruns(latest).reset_index(drop=True)], axis=1)
    warnings = early_warnings(latest, suite.thresholds)
    bands = rag_bands(panel)
    latest["rag"] = rag_status(latest, warnings, bands).to_numpy()
    latest["priority_index"] = priority_index(latest, warnings).to_numpy()
    latest["n_warnings"] = latest["project_id"].map(warnings.groupby("project_id").size()).fillna(0).astype(int)
    panel = panel.merge(latest[["project_id", "rag"]], on="project_id", how="left")

    log.info("Explainability (SHAP) and portfolio intelligence")
    shap_latest = shap_for_latest(suite, latest)
    sample = feats.sample(min(len(feats), 4000), random_state=settings.random_seed)
    gshap = global_shap(shap_for_latest(suite, sample))

    # systemic issues: from free-text remarks when the source has them, otherwise from figure-derived signals
    if pf.remarks_available(panel):
        issue_panel, issue_latest, labels, basis = panel, latest, pf.CATEGORY_LABELS, "remarks"
    else:
        issue_panel, issue_latest = pf.with_issue_signals(panel, latest)
        labels, basis = pf.SIGNAL_LABELS, "signals"
    freq = pf.bottleneck_frequency(issue_panel, labels=labels)
    impact = pf.bottleneck_impact(issue_panel, labels=labels)
    portfolio = {
        "issue_basis": basis,
        "bottleneck_frequency": freq, "bottleneck_impact": impact,
        "recurring": pf.recurring_bottlenecks(issue_panel, issue_latest, labels=labels),
        "by_ministry": pf.fingerprints(latest, "ministry"), "by_sector": pf.fingerprints(latest, "sector"),
        "by_state": pf.fingerprints(latest, "state"), "agencies": pf.entity_benchmark(latest, "implementing_agency"),
        "contractors": pf.entity_benchmark(latest, "contractor_name"),
        "patterns": pf.systemic_patterns(latest, impact, freq),
    }
    state = PrismState(
        panel=panel, latest=latest, trust=trust, warnings=warnings, suite=suite, shap_latest=shap_latest,
        global_shap=gshap, analogues=AnalogueIndex(feats), portfolio=portfolio,
        historical_interventions=raw["interventions"], as_of=panel["report_month"].max(),
        fingerprint=data_fingerprint(raw_dir), build_seconds=round(time.time() - t0, 1),
        meta={"n_projects": int(latest.shape[0]), "n_snapshots": int(panel.shape[0]), "version": PIPELINE_VERSION,
              "data_source": source, "data_dir": str(raw_dir), "files": raw["files"], "ingest_notes": raw["notes"],
              "first_month": panel["report_month"].min().strftime("%Y-%m"), "rag_bands": bands},
    )
    log.info("Pipeline built in %.1fs", state.build_seconds)
    return state


def load_or_build(force: bool = False) -> PrismState:
    source, raw_dir = resolve_source()
    if source == "synthetic" and not (raw_dir / "monthly_snapshots.csv").exists():
        from prism.data.generator import generate
        log.warning("No data found -- generating the synthetic PAIMANA/OCMS demo dataset in %s", raw_dir)
        generate(out_dir=raw_dir)
    log.info("Using %s data from %s", source, raw_dir)
    fp = data_fingerprint(raw_dir)
    cache = settings.artifact_dir / f"state_{source}_{fp}.joblib"
    if cache.exists() and not force:
        try:
            return joblib.load(cache)
        except Exception:  # corrupted / incompatible cache -> rebuild
            log.exception("Ignoring unreadable cache %s", cache)
    state = build_state(raw_dir, source)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    for old in settings.artifact_dir.glob("state_*.joblib"):
        old.unlink(missing_ok=True)
    joblib.dump(state, cache, compress=3)
    return state


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build (or rebuild) the PRISM pipeline state")
    parser.add_argument("--force", action="store_true", help="ignore the cache and retrain")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = load_or_build(force=args.force)
    print(f"{s.meta['data_source']} data from {s.meta['data_dir']}: {s.meta['n_projects']} projects, "
          f"{s.meta['n_snapshots']} snapshots, {s.meta['first_month']} to {s.as_of:%Y-%m}; built in {s.build_seconds}s")
    for n in s.meta["ingest_notes"]:
        print("  note:", n)
    print(s.latest["rag"].value_counts().to_dict())
