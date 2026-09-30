# Real PAIMANA / OCMS data

The `paimana_YYYY-MM.csv` files here are extracted from the Flash Report PDFs in
`data/reports/` (`python -m prism.data.pdf_import`). While this folder has data, the app uses it
instead of the synthetic demo data. To add more, drop CSV/Excel exports here as described below.

Drop your files **directly in this folder** (not in `templates/`) and PRISM uses them
instead of the synthetic demo data the next time it starts. You can also upload from
the app's **Data** page. When this folder is empty, the synthetic demo data in `data/raw/` is used.

Accepted formats are `.csv`, `.xlsx` and `.xls`.

## Two ways to organise the files

**A. One file per reporting month (simplest).** Each file has one row per project with
every column, like the PAIMANA monthly report tables. If a file has no month column, the
month is read from the file name, e.g. `2025-04.xlsx`, `PAIMANA_April_2025.csv`.
See `templates/one_month_all_columns_2025-04.csv`.

**B. Two files.**
* `project_master.csv`: one row per project (fixed details).
* `monthly_snapshots.csv`: one row per project per month.

See `templates/project_master.csv` and `templates/monthly_snapshots.csv`.

Any file here other than `project_master`, `macro_indicators` and `interventions_history`
is treated as monthly data, so you can also mix both layouts.

## Columns

| Needed for | Column | Also accepted as (examples) |
| --- | --- | --- |
| Project | `project_id` | Project ID, Project Code, OCMS ID |
| Project | `project_name` | Name of Project |
| Project | `ministry` | Ministry/Department |
| Project | `sector` | Sub-sector |
| Project | `state` | State/UT, Location |
| Project | `start_date` | Date of Start, Date of Sanction |
| Project | `original_completion` | Original Date of Completion |
| Project | `original_cost_cr` | Original Cost (Rs Cr), Sanctioned Cost |
| Monthly | `report_month` | Month, As on (or taken from the file name) |
| Monthly | `physical_progress_pct` | Physical Progress (%) |
| Monthly | `cumulative_expenditure_cr` | Cumulative Expenditure (Rs Cr), Expenditure |
| Monthly | `revised_cost_cr` | Anticipated Cost, Revised Cost, Latest Approved Cost |
| Monthly | `revised_completion` | Anticipated Date of Completion |
| Optional | `remarks` | Reasons for Delay (used for bottleneck analysis) |
| Optional | `status`, `implementing_agency`, `contractor_name`, `latitude`, `longitude` | Map positions default to the state centre |

Headers are matched case-insensitively, ignoring spaces and punctuation. Dates such as
`2025-04`, `01-04-2025`, `01/04/2025` and `Apr 2025` all work. Numbers such as
`"2,450.5"` and `Rs 980 Cr` are cleaned automatically.

Optional extra files: `macro_indicators.csv` (`month, cci_yoy_pct`) and
`interventions_history.csv` (`project_id, intervention_month, action_type, description, authority`).

## How much data is needed

The early-warning models learn from what happened **after** each past month, so they need
history. Plan on **24 or more consecutive months** for a few hundred projects. 12-month
warnings need at least 12 months of follow-up. With too little data, PRISM stops and tells
you which models don't have enough past events to learn from.

## Check before training

```bash
cd backend
python -m prism.data.check          # reads data/real/ and reports what it understood
python -m prism --force             # retrain on it
```

Force a source with `PRISM_DATA_SOURCE=real` or `PRISM_DATA_SOURCE=synthetic`.
