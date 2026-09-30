"""PAIMANA PRISM REST API (FastAPI).

Run:  uvicorn prism.api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import math
import re
import shutil
import tempfile
import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from prism.api.schemas import AskRequest, Health, InterventionCreate, ProjectPage
from prism.config import DIMENSIONS, HORIZONS, settings
from prism.engines import analytics
from prism.engines import interventions as ivx
from prism.engines import scenarios
from prism.engines.canonical import EXTENSIONS, load_raw, resolve_source, source_files
from prism.engines.evidence import action_queue, portfolio_evidence, project_evidence
from prism.engines.explain import drivers
from prism.engines.features import ALL_FEATURES
from prism.engines.forecasting import forecast_project
from prism.engines.llm import Assistant
from prism.engines.remarks import CATEGORY_LABELS
from prism.engines.trajectory import DIM_LABEL
from prism.engines.trust import ISSUE_LABELS, issue_log
from prism.events import EventBus
from prism.pipeline import PrismState, load_or_build

log = logging.getLogger("prism.api")


# --------------------------------------------------------------------------- runtime state
class Runtime:
    def __init__(self):
        self.state: PrismState | None = None
        self.error: str | None = None
        self.lock = threading.Lock()
        self.building = False
        self.store = ivx.InterventionStore(settings.db_path)
        self.events = EventBus(settings.db_path)
        self.assistant = Assistant()
        self._iv_cache: tuple[str, int, pd.DataFrame, dict] | None = None
        self.importing = False
        self.import_results: list[dict] = []
        self.watcher: FolderWatcher | None = None

    def build(self, force: bool = False, reason: str | None = None) -> None:
        with self.lock:
            if self.building:
                return
            self.building = True
        old = self.state
        started = time.time()
        if reason:
            self.events.publish("system", "Retraining models", severity="info", detail=reason)
        try:
            st = load_or_build(force=force)
            self.store.seed_historical(st.historical_interventions)
            self.state, self.error, self._iv_cache = st, None, None
            self._announce(old, st, started)
        except Exception as e:  # noqa: BLE001
            log.exception("Pipeline build failed")
            self.error = f"{type(e).__name__}: {e}"
            self.events.publish("system", "Retraining failed -- still showing the previous data", severity="high",
                                detail=self.error)
        finally:
            self.building = False

    def _announce(self, old: PrismState | None, st: PrismState, started: float) -> None:
        """Publish what changed after a build. At startup the feed is only seeded once (empty feed);
        after a retrain, genuinely new data announces the latest report's changes and model escalations."""
        try:
            if old is None:
                if self.events.count() == 0:
                    self.events.publish_many(analytics.change_events(analytics.month_changes(st.panel, st.latest)))
            else:
                if old.fingerprint != st.fingerprint:
                    self.events.publish_many(analytics.change_events(analytics.month_changes(st.panel, st.latest)))
                self.events.publish_many(analytics.state_diff(old.latest, st.latest, old.warnings, st.warnings))
                self.events.publish("system", "Models up to date", severity="info",
                                    detail=f"{st.meta.get('data_source', '')} data as of {st.as_of:%b %Y}, "
                                           f"{st.meta.get('n_projects')} projects; retrained in {time.time() - started:.0f}s.")
        except Exception:  # noqa: BLE001 -- the feed must never break the pipeline
            log.exception("Could not compute change events")
        if self.watcher:  # files written by this build/import are not "new" to the watcher
            self.watcher.snapshot = self.watcher.scan()
        # tells every open dashboard to refetch its data
        self.events.publish("system", "state_updated", data={"fingerprint": st.fingerprint,
                                                             "as_of": st.as_of.strftime("%Y-%m")}, persist=False)

    def build_async(self, force: bool = False, reason: str | None = None) -> None:
        threading.Thread(target=self.build, kwargs={"force": force, "reason": reason}, daemon=True).start()

    def import_and_build(self, reason: str) -> None:
        """Extract any new Flash Report PDFs, then retrain (used by the watcher and the Import button)."""
        from prism.data.pdf_import import import_reports
        self.importing = True
        try:
            self.import_results = import_reports(jobs=2)
            done = [r for r in self.import_results if r["status"] == "imported"]
            for r in done:
                self.events.publish("data", f"Imported {Path(r['file']).name}", severity="notice", month=r.get("month"),
                                    detail=f"{r.get('rows')} projects extracted for {r.get('month')}.")
        except Exception as e:  # noqa: BLE001
            self.import_results = [{"file": "-", "status": "error", "detail": str(e)}]
            self.events.publish("system", "PDF import failed", severity="high", detail=str(e))
        finally:
            self.importing = False
        self.build(force=True, reason=reason)

    def require(self) -> PrismState:
        if self.state is None:
            raise HTTPException(503, detail=self.error or "PRISM is training its models; retry shortly.")
        return self.state

    def interventions(self) -> tuple[pd.DataFrame, dict]:
        st = self.require()
        raw = self.store.list()
        key = (st.fingerprint, len(raw), int(raw["id"].max()) if len(raw) else 0)
        if self._iv_cache and self._iv_cache[0] == key:
            return self._iv_cache[1], self._iv_cache[2]
        control = ivx.control_baseline(st.panel, raw)
        ev = ivx.evaluate(raw, st.panel, control)
        self._iv_cache = (key, ev, control)
        return ev, control


class FolderWatcher:
    """Polls data/reports (PDFs) and data/real (CSV/Excel) and retrains when files are added or changed."""

    def __init__(self, runtime: "Runtime", interval: float):
        self.rt, self.interval = runtime, interval
        self.snapshot = self.scan()
        self.last_check: float | None = None
        self._stop = threading.Event()

    @staticmethod
    def scan() -> dict[str, tuple[int, int]]:
        files = {}
        for folder, patterns in ((settings.data_dir / "reports", ("*.pdf",)),
                                 (settings.real_dir, ("*.csv", "*.xlsx", "*.xls"))):
            if folder.is_dir():
                for pat in patterns:
                    for p in (folder.rglob(pat) if pat == "*.pdf" else folder.glob(pat)):
                        st = p.stat()
                        files[p.relative_to(settings.data_dir).as_posix()] = (st.st_size, int(st.st_mtime))
        return files

    def check(self) -> list[str]:
        """One polling step; returns the changed paths (and triggers import + retrain if any)."""
        self.last_check = time.time()
        now = self.scan()
        changed = sorted(k for k in now if self.snapshot.get(k) != now[k])
        removed = sorted(set(self.snapshot) - set(now))
        if not (changed or removed) or self.rt.building or self.rt.importing:
            return []
        self.snapshot = now
        for k in changed[:10]:
            self.rt.events.publish("data", f"New file detected: {Path(k).name}", severity="notice", detail=k)
        if removed:
            self.rt.events.publish("data", f"{len(removed)} file(s) removed", severity="info", detail=", ".join(removed[:5]))
        pdfs = any(k.lower().endswith(".pdf") for k in changed)
        reason = f"{len(changed) + len(removed)} file change(s) in data/"
        if pdfs:
            self.rt.import_and_build(reason)
        else:
            self.rt.build(force=True, reason=reason)
        self.snapshot = self.scan()  # the import itself writes CSVs into data/real
        return changed + removed

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:  # noqa: BLE001
                log.exception("Folder watcher step failed")

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True, name="prism-watcher").start()

    def stop(self) -> None:
        self._stop.set()


rt = Runtime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    rt.build_async()
    if settings.watch_interval_s > 0:
        rt.watcher = FolderWatcher(rt, settings.watch_interval_s)
        rt.watcher.start()
    yield
    if rt.watcher:
        rt.watcher.stop()


app = FastAPI(title="PAIMANA PRISM API", version="1.0.0", lifespan=lifespan,
              description="Predictive Risk Intelligence for Smart Infrastructure Monitoring -- "
                          "an AI decision-support layer over PAIMANA/OCMS project data.")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------- helpers
def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m")
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if math.isnan(v) or math.isinf(v) else round(float(v), 4)
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def records(df: pd.DataFrame, cols: list[str] | None = None) -> list[dict]:
    sub = df if cols is None else df[[c for c in cols if c in df.columns]]
    return [clean(r) for r in sub.to_dict(orient="records")]


SUMMARY_COLS = ["project_id", "project_name", "ministry", "sector", "state", "status", "rag", "trajectory",
                "risk_composite", "risk_cost", "risk_schedule", "risk_implementation", "risk_velocity", "priority_index",
                "progress", "cost_growth_pct", "slip_months", "original_cost_cr", "revised_cost_cr", "data_confidence",
                "confidence_grade", "n_warnings", "latitude", "longitude"]


def _project_or_404(st: PrismState, pid: str) -> pd.Series:
    try:
        return st.latest_row(pid)
    except KeyError:
        raise HTTPException(404, detail=f"Unknown project {pid}") from None


# --------------------------------------------------------------------------- system
@app.get("/api/health", response_model=Health, tags=["system"])
def health():
    llm = rt.assistant.client.status()
    if rt.state is None:
        return Health(status="error" if rt.error else "warming_up", detail=rt.error, llm=llm)
    return Health(status="ready", as_of=rt.state.as_of.strftime("%Y-%m"), build_seconds=rt.state.build_seconds, llm=llm,
                  data_source=rt.state.meta.get("data_source"), detail=rt.error, building=rt.building or rt.importing,
                  fingerprint=rt.state.fingerprint, watching=_watch_status())


def _watch_status() -> dict:
    w = rt.watcher
    return {"enabled": w is not None, "interval_s": settings.watch_interval_s,
            "folders": ["data/reports", "data/real"], "files": len(w.snapshot) if w else None,
            "last_check": time.strftime("%H:%M:%S", time.localtime(w.last_check)) if w and w.last_check else None,
            "listeners": rt.events.subscriber_count}


# --------------------------------------------------------------------------- live feed
@app.get("/api/events", tags=["live"])
def events(limit: int = Query(100, ge=1, le=500), kind: str | None = None):
    return rt.events.history(limit, kind)


@app.get("/api/events/stream", tags=["live"])
async def events_stream(request: Request, replay: int = Query(20, ge=0, le=200)):
    """Server-Sent Events: recent history first, then every new event as it happens."""
    sub = rt.events.subscribe()

    async def gen():
        try:
            yield "retry: 5000\n\n"
            for e in reversed(rt.events.history(replay)):
                yield f"id: {e['id']}\nevent: feed\ndata: {json.dumps(e, default=str)}\n\n"
            while True:
                try:
                    e = await asyncio.wait_for(sub[1].get(), timeout=15)
                    yield f"event: feed\ndata: {json.dumps(e, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected():
                    break
        finally:
            rt.events.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/changes/latest", tags=["live"])
def latest_changes():
    """What the latest monthly report changed versus each project's previous report."""
    st = rt.require()
    return clean({**analytics.month_changes(st.panel, st.latest), "watching": _watch_status()})


@app.get("/api/meta", tags=["system"])
def meta():
    st = rt.require()
    L = st.latest
    return clean({
        "as_of": st.as_of, "fingerprint": st.fingerprint, **st.meta,
        "ministries": sorted(L["ministry"].unique()), "sectors": sorted(L["sector"].unique()),
        "states": sorted(L["state"].unique()), "horizons": list(HORIZONS), "dimensions": list(DIMENSIONS),
        "dimension_labels": DIM_LABEL, "action_types": ivx.ACTION_TYPES, "bottleneck_labels": CATEGORY_LABELS,
        "llm": rt.assistant.client.status(),
    })


@app.post("/api/pipeline/rebuild", tags=["system"])
def rebuild():
    if rt.building:
        return {"status": "already_running"}
    rt.build_async(force=True, reason="Manual retrain requested")
    return {"status": "started"}


@app.get("/api/data/status", tags=["system"])
def data_status():
    """Which data the app is running on, and what is sitting in the data/real/ drop folder."""
    source, folder = resolve_source()
    real = settings.real_dir
    files = [{"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1)} for p in source_files(real)] if real.is_dir() else []
    st = rt.state
    return clean({
        "active_source": st.meta.get("data_source") if st else None, "configured_source": source,
        "real_folder": str(real), "real_files": files, "building": rt.building, "last_error": rt.error,
        "importing": rt.importing, "import_results": rt.import_results,
        "report_pdfs": sorted(str(p.relative_to(settings.data_dir / "reports"))
                              for p in (settings.data_dir / "reports").rglob("*.pdf")) if (settings.data_dir / "reports").is_dir() else [],
        "loaded": {k: st.meta.get(k) for k in ("data_dir", "files", "ingest_notes", "first_month", "n_projects")} if st else None,
        "as_of": st.as_of if st else None,
    })


@app.post("/api/data/upload", tags=["system"])
async def upload(files: list[UploadFile] = File(...)):
    """Add real PAIMANA/OCMS exports (CSV/Excel) to data/real/, validate them together with what is
    already there, then retrain in the background. Nothing is written if validation fails."""
    real = settings.real_dir
    tmp = Path(tempfile.mkdtemp())
    try:
        if real.is_dir():
            for p in source_files(real):
                shutil.copy(p, tmp / p.name)
        names = []
        for up in files:
            name = Path(up.filename or "upload.csv").name
            if Path(name).suffix.lower() not in EXTENSIONS:
                raise HTTPException(422, detail=f"{name}: only .csv, .xlsx or .xls files are accepted")
            (tmp / name).write_bytes(await up.read())
            names.append(name)
        try:
            raw = load_raw(tmp)
        except Exception as e:  # noqa: BLE001 -- report any parsing problem back to the user
            raise HTTPException(422, detail=f"Files not accepted: {e}") from None
        real.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy(tmp / n, real / n)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rt.events.publish("data", f"Uploaded {len(names)} file(s)", severity="notice", detail=", ".join(names))
    rt.build_async(force=True, reason="New data uploaded")
    return {"status": "accepted", "saved": names, "projects": int(raw["master"].shape[0]),
            "monthly_rows": int(raw["monthly"].shape[0]),
            "months": int(raw["monthly"]["report_month"].nunique()), "notes": raw["notes"],
            "detail": "Saved to data/real/; retraining on real data in the background."}


@app.post("/api/data/import-reports", tags=["system"])
def import_reports_ep():
    """Extract every Flash Report PDF under data/reports/ into data/real/, then retrain."""
    if rt.building or rt.importing:
        return {"status": "already_running"}

    def job():
        rt.import_and_build("Flash Report PDFs imported")

    threading.Thread(target=job, daemon=True).start()
    return {"status": "started"}


# --------------------------------------------------------------------------- portfolio
@app.get("/api/portfolio/summary", tags=["portfolio"])
def portfolio_summary():
    st = rt.require()
    L = st.latest
    live = L[L["status"] == "Ongoing"]
    w = st.warnings
    hist = st.panel[st.panel["status"] == "Ongoing"].groupby("report_month").agg(
        avg_risk=("risk_composite", "mean"), projects=("project_id", "nunique")).tail(24).reset_index()
    return clean({
        "as_of": st.as_of,
        "kpis": {
            "projects": len(L), "ongoing": len(live), "completed": int((L["status"] == "Completed").sum()),
            # cost figures cover ongoing projects, as in the Flash Report headline
            "original_cost_cr": live["original_cost_cr"].sum(), "revised_cost_cr": live["revised_cost_cr"].sum(),
            "expenditure_cr": live["expenditure"].sum(),
            "cost_escalation_pct": (live["revised_cost_cr"].sum() / live["original_cost_cr"].sum() - 1) * 100,
            "avg_risk": live["risk_composite"].mean(), "avg_data_confidence": L["data_confidence"].mean(),
            "delayed_projects": int((live["slip_months"] > 0).sum()),
            "cost_overrun_projects": int((live["cost_growth_pct"] > 0.5).sum()),
        },
        "rag": live["rag"].value_counts().to_dict(),
        "trajectory": live["trajectory"].value_counts().to_dict(),
        "warnings_by_horizon": {str(h): int(w.loc[w["horizon_months"] == h, "project_id"].nunique()) for h in HORIZONS},
        "warnings_by_dimension": {d: int(w.loc[w["dimension"] == d, "project_id"].nunique()) for d in DIMENSIONS},
        "risk_history": records(hist),
        "top_priority": records(live.sort_values("priority_index", ascending=False).head(10), SUMMARY_COLS),
        "risk_matrix": records(live, ["project_id", "project_name", "risk_composite", "risk_velocity", "rag", "revised_cost_cr", "trajectory"]),
        "patterns": st.portfolio["patterns"],
    })


@app.get("/api/portfolio/intelligence", tags=["portfolio"])
def portfolio_intelligence():
    st = rt.require()
    return clean({k: st.portfolio.get(k) for k in ("issue_basis", "bottleneck_frequency", "bottleneck_impact", "recurring",
                                                    "by_ministry", "by_sector", "by_state", "agencies", "contractors",
                                                    "patterns")})


@app.get("/api/portfolio/trends", tags=["portfolio"])
def portfolio_trends():
    st = rt.require()
    return clean(analytics.portfolio_trends(st.panel))


@app.get("/api/benchmark", tags=["analytics"])
def benchmark_groups(by: str = Query("ministry", pattern="^(ministry|sector|state|implementing_agency)$")):
    """Benchmarking & comparative analytics across ministries, sectors, states or agencies."""
    st = rt.require()
    return clean(analytics.benchmark(st.latest, st.panel, by))


@app.get("/api/drivers/cost", tags=["analytics"])
def cost_drivers():
    """Cost escalation driver analysis: where the overrun sits and what it is associated with."""
    st = rt.require()
    return clean(analytics.cost_drivers(st.latest, st.global_shap))


@app.get("/api/map", tags=["portfolio"])
def project_map():
    st = rt.require()
    return records(st.latest, ["project_id", "project_name", "ministry", "sector", "state", "status", "rag", "risk_composite",
                               "trajectory", "latitude", "longitude", "revised_cost_cr", "priority_index"])


# --------------------------------------------------------------------------- projects
@app.get("/api/projects", response_model=ProjectPage, tags=["projects"])
def list_projects(
    q: str | None = None, ministry: str | None = None, sector: str | None = None, state: str | None = None,
    rag: str | None = None, trajectory: str | None = None, status: str | None = "Ongoing",
    sort: str = "priority_index", order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0),
):
    st = rt.require()
    L = st.latest
    m = pd.Series(True, index=L.index)
    for col, val in (("ministry", ministry), ("sector", sector), ("state", state), ("rag", rag),
                     ("trajectory", trajectory), ("status", status)):
        if val and val != "all":
            m &= L[col].isin(val.split(","))
    if q:
        m &= L["project_id"].str.contains(q, case=False, regex=False) | L["project_name"].str.contains(q, case=False, regex=False)
    sub = L[m]
    if sort not in SUMMARY_COLS:
        raise HTTPException(422, detail=f"Cannot sort by {sort}")
    sub = sub.sort_values(sort, ascending=order == "asc")
    return {"total": int(len(sub)), "items": records(sub.iloc[offset: offset + limit], SUMMARY_COLS)}


@app.get("/api/projects/{pid}", tags=["projects"])
def project_detail(pid: str):
    st = rt.require()
    r = _project_or_404(st, pid)
    probs = {d: {str(h): r[f"p_{d}_{h}"] for h in HORIZONS} for d in DIMENSIONS}
    thr = {d: {str(h): st.suite.thresholds[(d, h)] for h in HORIZONS} for d in DIMENSIONS}
    extra = ["implementing_agency", "contractor_name", "start_date", "original_completion", "revised_completion",
             "report_month", "expenditure", "expenditure_ratio", "expected_progress", "completion_gap", "velocity_3m",
             "velocity_6m", "required_velocity", "n_cost_revisions", "n_schedule_revisions", "risk_acceleration",
             "bottleneck", "bottleneck_streak", "staleness_months", "n_contradictions", "n_anomalies", "missingness_pct",
             "completeness_score", "freshness_score", "consistency_score", "stability_score",
             "cost_q10", "cost_q50", "cost_q90", "time_q10", "time_q50", "time_q90",
             "contractor_credit_score", "land_acquisition_friction_score", "weather_geopolitical_risk_index"]
    base = {c: r[c] for c in SUMMARY_COLS + extra if c in r.index}
    base["bottleneck_label"] = CATEGORY_LABELS.get(r["bottleneck"], r["bottleneck"])
    return clean({**base, "probabilities": probs, "thresholds": thr,
                  "warnings": records(st.warnings[st.warnings["project_id"] == pid])})


@app.get("/api/projects/{pid}/timeseries", tags=["projects"])
def project_timeseries(pid: str):
    st = rt.require()
    _project_or_404(st, pid)
    h = st.history(pid)
    cols = ["report_month", "progress", "physical_progress_pct", "expected_progress", "expenditure", "revised_cost_cr",
            "cost_growth_pct", "slip_months", "velocity_3m", "risk_composite", "risk_cost", "risk_schedule",
            "risk_implementation", "risk_velocity", "trajectory", "bottleneck", "remarks",
            *[f"p_{d}_{hz}" for d in DIMENSIONS for hz in HORIZONS]]
    return records(h, cols)


@app.get("/api/projects/{pid}/forecast", tags=["projects"])
def project_forecast(pid: str, horizon: int = Query(12, ge=3, le=36)):
    st = rt.require()
    r = _project_or_404(st, pid)
    fc = forecast_project(st.history(pid), horizon)
    fc["overrun"] = {k: r.get(k) for k in ("cost_q10", "cost_q50", "cost_q90", "time_q10", "time_q50", "time_q90")}
    fc["revised_cost_cr"] = r["revised_cost_cr"]
    fc["original_cost_cr"] = r["original_cost_cr"]
    return clean(fc)


@app.get("/api/projects/{pid}/explain", tags=["projects"])
def project_explain(pid: str, horizon: int = Query(6)):
    st = rt.require()
    _project_or_404(st, pid)
    if horizon not in HORIZONS:
        raise HTTPException(422, detail=f"horizon must be one of {HORIZONS}")
    pos = st.latest.index[st.latest["project_id"] == pid][0]
    x = st.latest.loc[pos, ALL_FEATURES]
    return clean({d: drivers(st.shap_latest[(d, horizon)][pos], x, top_n=8) for d in DIMENSIONS})


@app.get("/api/projects/{pid}/analogues", tags=["projects"])
def project_analogues(pid: str, k: int = Query(5, ge=1, le=15)):
    st = rt.require()
    r = _project_or_404(st, pid)
    return clean(st.analogues.query(r, k))


@app.get("/api/projects/{pid}/scenarios", tags=["projects"])
def project_scenarios(pid: str):
    st = rt.require()
    return clean(scenarios.run(st.suite, _project_or_404(st, pid)))


@app.get("/api/projects/{pid}/trust", tags=["projects"])
def project_trust(pid: str):
    st = rt.require()
    r = _project_or_404(st, pid)
    return clean({"score": {k: r[k] for k in ("data_confidence", "confidence_grade", "completeness_score", "freshness_score",
                                              "consistency_score", "stability_score", "staleness_months", "n_contradictions",
                                              "n_anomalies", "missingness_pct")},
                  "issues": issue_log(st.panel, pid, limit=100)})


@app.get("/api/projects/{pid}/evidence", tags=["projects"])
def project_evidence_ep(pid: str):
    st = rt.require()
    _project_or_404(st, pid)
    ev, _ = rt.interventions()
    return clean(project_evidence(st, pid, records(ev[ev["project_id"] == pid])))


# --------------------------------------------------------------------------- warnings & trust
@app.get("/api/warnings", tags=["warnings"])
def warnings(horizon: int | None = None, dimension: str | None = None, severity: str | None = None,
             ministry: str | None = None, limit: int = Query(500, ge=1, le=5000)):
    st = rt.require()
    w = st.warnings.merge(st.latest[["project_id", "project_name", "ministry", "sector", "state", "rag",
                                     "risk_composite", "priority_index", "data_confidence"]], on="project_id")
    if horizon:
        w = w[w["horizon_months"] == horizon]
    if dimension:
        w = w[w["dimension"] == dimension]
    if severity:
        w = w[w["severity"] == severity]
    if ministry:
        w = w[w["ministry"] == ministry]
    w = w.sort_values(["horizon_months", "priority_index"], ascending=[True, False])
    return records(w.head(limit))


@app.get("/api/trust", tags=["trust"])
def trust_overview():
    st = rt.require()
    L = st.latest
    flags = [c for c in st.panel.columns if c.startswith("flag_")]
    return clean({
        "avg_confidence": L["data_confidence"].mean(),
        "grades": L["confidence_grade"].value_counts().to_dict(),
        "stale_projects": int((L["staleness_months"] > 0).sum()),
        "issue_rates": {c.removeprefix("flag_"): float(st.panel[c].mean()) for c in flags},
        "issue_labels": ISSUE_LABELS,
        "lowest_confidence": records(L.sort_values("data_confidence").head(25),
                                     ["project_id", "project_name", "ministry", "status", "data_confidence", "confidence_grade",
                                      "staleness_months", "n_contradictions", "n_anomalies", "missingness_pct", "last_report_month"]),
        "recent_issues": issue_log(st.panel, limit=150),
    })


# --------------------------------------------------------------------------- models
@app.get("/api/models/benchmark", tags=["models"])
def benchmark():
    st = rt.require()
    s = st.suite
    return clean({
        "classification": s.benchmark, "significance": s.significance, "cuf_sufficiency": s.cuf_sufficiency,
        "lead_times": s.lead_times, "regression": s.regression_metrics, "permutation_importance": s.permutation,
        "global_shap": st.global_shap, "base_rates": s.base_rates,
        "thresholds": {f"{d}_{h}": t for (d, h), t in s.thresholds.items()},
        "split": {k: len(v) for k, v in s.split.items()},
    })


# --------------------------------------------------------------------------- interventions
@app.get("/api/interventions", tags=["interventions"])
def list_interventions(project_id: str | None = None, source: str | None = None, limit: int = Query(300, ge=1, le=5000)):
    ev, control = rt.interventions()
    st = rt.require()
    if project_id:
        ev = ev[ev["project_id"] == project_id]
    if source:
        ev = ev[ev["source"] == source]
    ev = ev.merge(st.latest[["project_id", "project_name", "ministry"]], on="project_id", how="left")
    done = ev[ev["outcome"].isin(["Improved", "Worsened", "No material change"])]
    return clean({
        "control": control, "effectiveness": ivx.effectiveness(ev, control),
        "outcomes": ev["outcome"].value_counts().to_dict(), "n_evaluated": len(done),
        "items": records(ev.head(limit)),
        "caveat": "Observational comparison against comparable non-intervened situations; not a causal estimate.",
    })


@app.get("/api/interventions/queue", tags=["interventions"])
def intervention_queue(limit: int = Query(15, ge=1, le=50)):
    """Action queue: top-priority projects with no decision recorded in the last 3 months."""
    st = rt.require()
    raw = rt.store.list()
    cutoff = (st.as_of - pd.DateOffset(months=3)).strftime("%Y-%m")
    recent = set(raw.loc[raw["intervention_month"] >= cutoff, "project_id"]) if len(raw) else set()
    return clean(action_queue(st, recent, limit))


@app.post("/api/interventions", tags=["interventions"], status_code=201)
def create_intervention(body: InterventionCreate):
    st = rt.require()
    r = _project_or_404(st, body.project_id)
    month = body.intervention_month or st.as_of.strftime("%Y-%m")
    row = rt.store.add(body.project_id, month, body.action_type, body.description, body.authority,
                       float(r["risk_composite"]))
    rt.events.publish("decision", f"Decision recorded: {ivx.ACTION_TYPES.get(body.action_type, body.action_type)}",
                      severity="notice", project_id=body.project_id,
                      detail=f"{r['project_name']}: {body.description} (risk at decision {float(r['risk_composite']):.1f})")
    return clean(row)


@app.delete("/api/interventions/{iid}", tags=["interventions"])
def delete_intervention(iid: int):
    if not rt.store.delete(iid):
        raise HTTPException(404, detail="Not found (historical records cannot be deleted)")
    return {"deleted": iid}


# --------------------------------------------------------------------------- assistant
_STOP = {"project", "projects", "what", "which", "when", "where", "about", "status", "risk", "with", "from", "this",
         "that", "their", "there", "will", "complete", "completion", "delay", "delayed", "cost", "should", "construction",
         "development", "phase", "line", "road", "section", "national", "highway", "railway", "tell", "explain", "show",
         # words of portfolio-level questions that also occur in a few project names
         "report", "reports", "latest", "changed", "change", "changes", "month", "monthly", "summary", "portfolio",
         "overall", "total", "attention", "first", "priority", "warning", "warnings", "issues", "issue", "recurring",
         "sector", "sectors", "ministry", "ministries", "state", "states", "agency", "agencies", "riskiest", "worst",
         "overrun", "overruns", "slippage", "slipped", "revised", "revision", "revisions", "progress", "stalled",
         "compare", "common", "trend", "trends", "happened", "recent", "recently", "update", "updates", "how", "many"}


def _project_from_question(st: PrismState, question: str) -> str | None:
    """Scope a question to one project when it names its ID (PM-612068 / N24001425 / PRJ-00001) or,
    failing that, distinctive words of its name (e.g. "Polavaram")."""
    q = question.upper()
    for rx in (r"\b(?:PM|PRJ|OCMS)-[A-Z0-9]+\b", r"\bN\d{8}\b", r"\b\d{6}\b"):
        for m in re.findall(rx, q):
            for cand in (m, f"PM-{m}", f"OCMS-{m}"):
                if (st.latest["project_id"] == cand).any():
                    return cand
    words = [w for w in re.findall(r"[a-z0-9]{5,}", question.lower()) if w not in _STOP]
    if not words:
        return None
    names = st.latest["project_name"].str.lower()
    hits = sum(names.str.contains(rf"\b{re.escape(w)}", regex=True).astype(int) for w in words)
    best = hits.max()
    if best == 0 or (hits == best).sum() > 3:
        return None
    cands = st.latest[hits == best].sort_values("priority_index", ascending=False)
    return str(cands["project_id"].iloc[0])


# --------------------------------------------------------------------------- local LLM (Ollama)
_llm_job: dict = {"state": "idle", "status": None, "percent": None, "error": None}


def _llm_status(refresh: bool = False) -> dict:
    return {**rt.assistant.client.status(refresh=refresh), "job": dict(_llm_job)}


@app.get("/api/llm/status", tags=["assistant"])
def llm_status(refresh: bool = False):
    """Is Ollama running, is the model downloaded, and what to do next."""
    return _llm_status(refresh)


@app.post("/api/llm/pull", tags=["assistant"])
def llm_pull():
    """Download the configured model through Ollama in the background (progress goes to the live feed)."""
    client = rt.assistant.client
    if _llm_job["state"] == "pulling":
        return _llm_status()
    if client.status(refresh=True)["step"] == "not_running":
        raise HTTPException(409, f"Ollama is not running at {client.host}. Install/start Ollama first.")

    def run():
        last = {"t": 0.0, "pct": -10}
        _llm_job.update(state="pulling", status="starting", percent=None, error=None)
        rt.events.publish("system", f"Downloading LLM model {client.model}", severity="notice")

        def progress(status, pct):
            _llm_job.update(status=status, percent=pct)
            if pct is not None and pct - last["pct"] >= 25 and time.time() - last["t"] > 2:
                last.update(t=time.time(), pct=pct)
                rt.events.publish("system", f"Downloading {client.model}: {pct}%", persist=False)

        try:
            client.pull(progress)
            _llm_job.update(state="warming", status="loading model")
            try:
                client.warm()
            except Exception as e:  # noqa: BLE001 -- the model is there; warming is best effort
                log.warning("LLM warm-up failed: %s", e)
            _llm_job.update(state="done", status="ready", percent=100)
            rt.events.publish("system", f"LLM ready: {client.model}", severity="notice",
                              detail="The assistant now writes answers with the local LLM (still grounding-checked).")
        except Exception as e:  # noqa: BLE001
            _llm_job.update(state="failed", error=str(e))
            rt.events.publish("system", f"LLM download failed: {client.model}", severity="high", detail=str(e))
        rt.events.publish("system", "state_updated", persist=False)

    threading.Thread(target=run, daemon=True, name="prism-llm-pull").start()
    return _llm_status()


@app.post("/api/llm/test", tags=["assistant"])
def llm_test():
    """Ask one fixed portfolio question and report which engine answered."""
    st = rt.require()
    rt.assistant.client.status(refresh=True)
    res = rt.assistant.answer("Give me a portfolio summary", portfolio_evidence(st))
    return clean({"engine": res["engine"], "latency_ms": res["latency_ms"], "answer": res["answer"],
                  "grounded": res["grounding"]["grounded"], "llm": res["llm"]})


@app.post("/api/assistant/ask", tags=["assistant"])
def ask(body: AskRequest):
    st = rt.require()
    pid = body.project_id
    if not pid:
        pid = _project_from_question(st, body.question)
    if pid:
        _project_or_404(st, pid)
        ev, _ = rt.interventions()
        evidence = project_evidence(st, pid, records(ev[ev["project_id"] == pid]))
    else:
        evidence = portfolio_evidence(st)
    res = rt.assistant.answer(body.question, evidence, body.history)
    return clean({**res, "scope": evidence["scope"], "project_id": pid, "evidence_count": len(evidence["items"])})
