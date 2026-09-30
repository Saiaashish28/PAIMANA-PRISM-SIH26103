"""Real-data ingestion: messy PAIMANA-style exports must load to exactly the same values."""
import pandas as pd
import pytest

from prism.engines.canonical import load_raw, month_from_filename
from prism.engines.features import build_features
from prism.engines.trust import clean_and_flag
from prism.engines.canonical import build_canonical
from prism.pipeline import check_history


@pytest.fixture(scope="module")
def messy_dir(raw_dir, tmp_path_factory):
    """Rewrite the synthetic data as one PAIMANA-style Excel/CSV file per month, no master file."""
    d = tmp_path_factory.mktemp("real")
    m = pd.read_csv(raw_dir / "project_master.csv")
    s = pd.read_csv(raw_dir / "monthly_snapshots.csv").merge(m, on="project_id")
    s = s[s["report_month"] >= "2022-01-01"]
    dmy = lambda c: pd.to_datetime(c).dt.strftime("%d-%m-%Y")  # noqa: E731
    out = pd.DataFrame({
        "Project ID": s["project_id"], "Name of Project": s["project_name"], "Ministry/Department": s["ministry"],
        "Sector": s["sector"], "State/UT": s["state"], "Date of Start": dmy(s["start_date"]),
        "Original Date of Completion": dmy(s["original_completion"]),
        "Original Cost (Rs Cr)": s["original_cost_cr"].map(lambda v: f"{v:,.2f}"),
        "Anticipated Cost (Rs Cr)": s["revised_cost_cr"].map(lambda v: f"{v:,.2f}"),
        "Anticipated Date of Completion": pd.to_datetime(s["revised_completion"]).dt.strftime("%b %Y"),
        "Cumulative Expenditure (Rs Cr)": s["cumulative_expenditure_cr"], "Physical Progress (%)": s["physical_progress_pct"],
        "Reasons for Delay": s["remarks"], "_m": s["report_month"]})
    for i, (mo, g) in enumerate(out.groupby("_m")):
        name = f"PAIMANA_{pd.Timestamp(mo):%B_%Y}" + (".xlsx" if i % 2 else ".csv")
        g = g.drop(columns="_m")
        g.to_excel(d / name, index=False) if name.endswith("xlsx") else g.to_csv(d / name, index=False)
    return d, m, s


def test_month_from_filename():
    assert month_from_filename("PAIMANA_April_2025.xlsx") == pd.Timestamp(2025, 4, 1)
    assert month_from_filename("report-2024-11.csv") == pd.Timestamp(2024, 11, 1)
    assert month_from_filename("projects.csv") is None


def test_messy_export_round_trips(messy_dir):
    d, m, s = messy_dir
    r = load_raw(d)
    x = r["master"].merge(m.assign(start_date=pd.to_datetime(m["start_date"])), on="project_id", suffixes=("", "_o"))
    assert len(x) == r["master"].shape[0] > 0
    assert (x["start_date"] == x["start_date_o"]).all()
    assert ((x["original_cost_cr"] - x["original_cost_cr_o"]).abs() < 0.01).all()
    y = r["monthly"].merge(s.assign(report_month=pd.to_datetime(s["report_month"])), on=["project_id", "report_month"],
                           suffixes=("", "_o"))
    assert len(y) == len(s)
    assert ((y["revised_cost_cr"] - y["revised_cost_cr_o"]).abs() < 0.01).all()
    assert (y["revised_completion"] == pd.to_datetime(y["revised_completion_o"])).all()
    assert r["master"]["latitude"].notna().all()


def test_too_little_history_is_reported(messy_dir):
    d, _, _ = messy_dir
    r = load_raw(d)
    r["monthly"] = r["monthly"][r["monthly"]["report_month"] >= r["monthly"]["report_month"].max() - pd.DateOffset(months=2)]
    with pytest.raises(ValueError, match="Not enough history"):
        check_history(build_features(clean_and_flag(build_canonical(r))))


def test_missing_required_column_is_explained(tmp_path):
    pd.DataFrame({"Project ID": ["A"], "Month": ["2025-01"]}).to_csv(tmp_path / "x.csv", index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_raw(tmp_path)
