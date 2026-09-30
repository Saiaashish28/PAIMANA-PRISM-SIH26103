# PAIMANA PRISM — Predictive Risk Intelligence for Smart Infrastructure Monitoring

**SIH 2026 · Problem Statement 26103** (MoSPI / DIID, *Use case on web-based integrated project-monitoring platform*) · Theme: Smart Automation · Team **Cypher Knights**

PRISM is an AI decision-support layer over PAIMANA/OCMS data. It turns the monthly Flash Reports into an early-warning and prioritisation system, and it runs on **real PAIMANA data**: 24 monthly Flash Reports (Jun 2024 – Aug 2026), 3,076 projects and 46,547 project-months, extracted from the PDFs in `data/reports/`.

| Problem-statement outcome | Where in PRISM |
| --- | --- |
| a. Cost overrun prediction model | Cost-escalation early warnings (3/6/12 months) + quantile model of final cost growth (P10/P50/P90) |
| b. Time overrun prediction model | Schedule-slip early warnings + final time-overrun model + statsmodels completion forecast |
| c. Project risk scoring framework | Composite risk 0–100, Red/Amber/Green calibrated on history, risk trajectory, Priority Attention Index |
| d. Early warning alert system | Calibrated alerts per dimension × horizon, velocity-drop anomalies · *Early warnings* page |
| e. Benchmarking & comparative analytics | Ministry / sector / state / implementing-agency comparison and trends · *Benchmarking* page |
| f. Cost escalation driver analysis | Overrun concentration (Pareto), delay–cost link, statsmodels OLS drivers, SHAP · *Cost drivers* page |
| g. AI-powered monitoring dashboard | React dashboard: overview, trends, project pages, map, warnings, models, data trust |
| h. LLM-enabled project assistant | Local Ollama **Qwen 2.5 3B** + Evidence Packager + Grounding Validator (works offline without the LLM) |
| i. Documentation & deployment | This README, OpenAPI docs at `/docs`, `docker-compose.yml`, pytest suite |

Technical dimensions: **(a)** statistical and ML models for cost, time and implementation risk; **(b)** an AI/ML vs conventional-statistics benchmark with significance tests, lead times and false alarms; **(c)** CUF sufficiency, meaning CUF fields alone vs CUF plus variables the CUF doesn't capture.

## Results on the real PAIMANA data

Models are evaluated on **769 held-out projects** that took no part in training. Projects are split 60/15/25 into train, calibrate and test sets, never by row.

| Finding | Result |
| --- | --- |
| Early-warning accuracy (XGBoost ROC-AUC) | **0.77 – 0.89** across the 9 models (cost / schedule / implementation × 3, 6, 12 months) |
| (b) AI/ML vs conventional statistics | XGBoost beats logistic regression **significantly on all 9 models**: +0.09 to +0.16 AUC (project-clustered bootstrap, p < 0.01) |
| Early-warning lead time (12-month models) | Schedule revisions: 97% flagged in advance, mean **11.3 months** ahead, 29% false-alarm rate (logistic regression: 37%). Cost revisions: 59% flagged at a **9%** false-alarm rate (logistic regression: 87% detected but 41% false alarms) |
| (c) CUF sufficiency | Adding non-CUF context gives a **significant uplift on all 9 models** (+0.02 to +0.10 AUC). The context variables are the implementing agency's, state's and sector's track record on *other* projects, derived point-in-time |
| Final-overrun regression | Hard to beat the naive "no further growth" baseline (cost MAE 7.0 vs 6.1 pp; time 11.5 vs 11.6 months). Reported as-is: two years of history is short for predicting final outcomes |
| Cost escalation drivers | ₹3.8 lakh Cr overrun across 458 ongoing projects, **104 of which account for 80%**. Water resources (26%) and railways (24%) lead. Each month of slippage is associated with +0.7 pp cost growth (OLS, p < 0.001) |

The extraction was checked against the official figures: `FlashReport_April2026.pdf` reproduces exactly 1,981 ongoing projects, ₹37.13 / ₹42.78 / ₹20.36 lakh Cr (original cost / revised cost / expenditure), 17 ministries and 22 sectors. A test covers this.

## Quick start

Requirements: Python ≥ 3.11 and Node ≥ 20. [Ollama](https://ollama.com) is optional.

**One command.** It creates `backend/.venv`, installs everything, frees port 8000, starts the API and the dashboard, and opens the browser.

```powershell
# Windows (PowerShell, in the repo folder)
powershell -ExecutionPolicy Bypass -File .\start.ps1
```
```bash
# macOS / Linux
./start.sh
```

The dashboard opens at http://localhost:5173 and the API docs at http://localhost:8000/docs. The first start trains every model (~2 min); after that the models are cached.

### Run the app locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements.txt
# macOS / Linux: . .venv/bin/activate && python -m pip install -r requirements.txt
python -m uvicorn prism.api.main:app --port 8000
```

Then in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Always start uvicorn with the *same* Python that installed the packages (`python -m uvicorn`). This avoids `ModuleNotFoundError`.

### Run tests

The repo includes a pytest suite, but the test dependencies are kept in `backend/requirements-dev.txt` and must be installed separately:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\python -m pip install -r requirements-dev.txt
# macOS / Linux: . .venv/bin/activate && python -m pip install -r requirements-dev.txt
python -m pytest -q
```

If you only install `requirements.txt`, the tests will not run because `pytest` is not part of the runtime requirements.

<details><summary>Manual start</summary>

```bash
cd backend
python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python
.venv/bin/python -m uvicorn prism.api.main:app --port 8000
cd ../frontend && npm install && npm run dev
```
Always start uvicorn with the *same* Python that installed the packages (`python -m uvicorn`). This avoids `ModuleNotFoundError`.
</details>

**Assistant.** Open *Assistant* in the sidebar. Click an example question or type your own, e.g. "What changed in the latest report?", "Which projects need attention first?" or "What is the status of Polavaram?". Pick a project under *Scope* for detailed project answers.

### Using Ollama (optional local LLM)

Without an LLM, the assistant composes answers straight from the evidence. With Ollama, **Qwen 2.5 3B** writes fluent answers. They are still checked number by number by the grounding validator.

1. Install Ollama from https://ollama.com/download. On Windows it then runs from the system tray.
2. Download the model once (~2 GB): `ollama pull qwen2.5:3b`. `start.ps1` / `start.sh` do this automatically when Ollama is installed.
3. Open *Assistant*. The **Local LLM (Ollama)** card shows a checklist; click **Check again**, then **Test LLM**. If Ollama is running without the model, **Download model** fetches it from the dashboard. Answers written by the LLM carry a purple "Written by qwen2.5:3b" badge.

**Troubleshooting**
* The card shows the address PRISM uses (default `http://127.0.0.1:11434`). To point PRISM elsewhere, set `PRISM_OLLAMA_HOST` (forms like `0.0.0.0` or `host:port` are accepted).
* On a CPU-only laptop the first answer loads the model and can take about a minute. The timeout is 180 s (`PRISM_OLLAMA_TIMEOUT`).
* Use `PRISM_OLLAMA_MODEL` to try another model (e.g. `qwen2.5:7b`).

Or with Docker: `docker compose up --build` (dashboard http://localhost:8080). This runs Ollama and pulls `qwen2.5:3b` once.

## Live feed

PRISM watches `data/reports/` (PDFs) and `data/real/` (CSV/Excel) every 30 s (`PRISM_WATCH_INTERVAL`; 0 disables it). When you drop in a new Flash Report:

1. **New file detected**: the PDF is extracted into `data/real/`.
2. The models retrain in the background while the dashboard keeps serving the previous results.
3. The feed publishes what the new report changed: schedule slips, cost revisions, completions and new projects. It also publishes model escalations: projects now Red, new critical warnings, and trajectories turning *Rapidly Deteriorating*.
4. Every open dashboard refreshes by itself over Server-Sent Events (`/api/events/stream`). No reload is needed.

The header shows a **● Live** indicator and a notification bell, and high-severity events pop up as toasts. The *Live feed* page lists the latest report's changes and the full activity timeline. Events are stored in SQLite, so the history survives restarts.

## Data

```
data/reports/   Flash Report PDFs, as published (input)
data/real/      one extracted table per month: paimana_YYYY-MM.csv (used by the app)
data/raw/       synthetic demo data, generated only when data/real/ is empty (not committed)
```

To add a new month, put the PDF in `data/reports/` and either click **Data sources → Import PDFs & retrain**, or run:

```bash
cd backend
python -m prism.data.pdf_import    # PDFs -> data/real/ (cached per month; --force to redo)
python -m prism.data.check         # what was understood + whether there is enough history
python -m prism --force            # retrain
```

**What is imported.**

| Report | Imported |
| --- | --- |
| PAIMANA Flash Reports (2025+) and MoSPI "List of Tables" Flash Reports (2024 – early 2025) | Project tables |
| Quarterly QPISR reports | Only for months without a monthly report |
| OCMS 2020–23 reports | Not yet: no physical-progress column |
| Review / synopsis reports | No project-level tables |

`data/reports/README.md` has the details.

**Linking across months.**
* Projects are linked by PAIMANA code.
* Older reports link through the legacy OCMS code, or through an identical sanctioned cost plus a similar name.
* Months without a report become explicit gaps (never treated as "no progress").
* Projects that leave the list are closed as Completed (≥ 95% progress) or Dropped.

CSV/Excel exports can also be used directly; see `data/real/README.md` for accepted column names.

## How it works

```
Flash Report PDFs ─► PDF importer ─► Canonical monthly panel ─► Data Trust (rules + IsolationForest)
    ─► point-in-time features ─► XGBoost early-warning models (3 risks × 3 horizons, benchmarked)
    ─► risk trajectory (velocity, acceleration) ─► warnings · RAG · Priority index
    ─► SHAP / analogues / forecasts / scenarios ─► Evidence Packager ─► Qwen 2.5 3B + Grounding Validator
    ─► decision record ─► outcome monitor (closed loop)
```

**Labels without look-ahead.** Features for month *t* use only what was reported up to *t*. A test checks this by truncating the data. Labels look *h* months ahead:
* **Cost:** growth rises by ≥ 5 pp.
* **Schedule:** revised completion slips by ≥ 3 more months.
* **Implementation stall:** progress below a quarter of the planned pace.

A window counts only if the project actually reported at both ends.

**Alerts and RAG.**
* Alert thresholds are tuned on the calibration projects. 3-month alerts favour precision (F0.7); 6- and 12-month alerts are balanced (F1).
* A 3-month stall alert is *Critical* only when the 6-month model agrees, because physical progress is reported in lumps.
* Red/Amber bands are the 85th / 60th percentiles of historical risk. A deteriorating portfolio therefore shows more Reds, rather than a fixed share.

**Grounded assistant.** Every answer is built from citable evidence items (E1…En). The validator checks each number and citation against the evidence. A failing LLM answer gets one retry and then falls back to a deterministic evidence-composed answer.

## Tech stack

| Layer | Implementation |
| --- | --- |
| Data & statistics | Python, pandas, NumPy, SciPy, **statsmodels** (Holt / ARIMA forecasts, OLS driver model), pdfplumber |
| Predictive ML | **XGBoost** (production), **HistGradientBoosting** (challenger), logistic regression (baseline), **IsolationForest**, quantile GBM |
| Explainability | **SHAP**, **permutation importance**, risk-trajectory engine |
| Backend | **FastAPI**, **Pydantic**, **Uvicorn**, SQLite (decision records, event history), Server-Sent Events |
| LLM | **Ollama + Qwen 2.5 3B**, Evidence Packager, Grounding Validator |
| Frontend | **React**, **TypeScript**, **Tailwind CSS**, **Vite**, **Apache ECharts**, **Leaflet** |

## Repository layout

```
backend/prism/
  data/pdf_import.py        Flash Report PDF extraction, cross-era project linking
  data/check.py             validate a data folder without training
  data/generator.py         synthetic demo data (only when no real data is present)
  engines/canonical.py      loading, column matching, gaps, project lifecycle
  engines/trust.py          Data Trust engine and confidence score
  engines/features.py       point-in-time features, portfolio-context variables, labels
  engines/risk_models.py    models, benchmark, significance, CUF sufficiency, lead times
  engines/trajectory.py     risk velocity/acceleration, warnings, RAG
  engines/analytics.py      trends, benchmarking, cost-driver analysis
  engines/…                 SHAP, forecasting, analogues, scenarios, portfolio, interventions, evidence, LLM
  pipeline.py · api/main.py orchestration + cache · REST API
backend/tests/              pytest (leakage, PDF parsing vs official totals, grounding, API)
backend/prism/events.py     live event bus (SQLite + Server-Sent Events)
frontend/src/pages/         Overview, Live feed, Trends, Warnings, Projects, Project, Map, Benchmarking, Cost drivers,
                            Systemic patterns, Model benchmark, Interventions, Assistant, Data trust, Data sources
docs/                       problem statement and pipeline design
```

## Limitations

* The PDFs carry no free-text remarks. On Flash Report data, *Systemic patterns* therefore analyses issue signals derived from the reported figures (stalled, overdue, recent slip, cost revision, spend ahead of progress, behind plan). With remark-bearing CSV/Excel exports it analyses the reported bottlenecks instead.
* History is 27 months, with some short or missing editions (e.g. Jul–Nov 2025 list only about 800 projects). The 2020–23 OCMS reports would add depth but lack physical progress.
* Some report figures are inconsistent between editions (e.g. revised cost below original). They are shown as published. The Data Trust engine flags contradictions and anomalies.
* Scenario analysis and intervention effects are associations, not causal estimates. The UI says so.
* Map positions are state centroids (the reports give no coordinates). Map tiles need internet access or an internal tile server.
