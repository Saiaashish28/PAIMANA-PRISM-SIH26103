from pathlib import Path

import pandas as pd
import pytest

from prism.data.pdf_import import _month, _parse_name, harmonise, link_project_ids, parse_table

REPO = Path(__file__).resolve().parents[2]
APRIL_2026 = REPO / "data/reports/Project Monitoring/2025-2027/FlashReport_April2026.pdf"


@pytest.mark.parametrize("tok,expected", [
    ("03/2023", "2023-03"), ("(07/2026)", "2026-07"), ("3-2021", "2021-03"), ("(Aug-25)", "2025-08"),
    ("{8/2025}", "2025-08"), ("(N.A.)", None), ("-", None), ("Mar 2025", "2025-03"),
])
def test_month_tokens(tok, expected):
    assert _month(tok) == expected


def test_name_cell_paimana_layout():
    info = _parse_name("Construction of New Domestic Terminal Building at Rajahmundry Airport.\n"
                       "(Airport Authority of India [AAI])\n(701121)\n(N04000103) (-)")
    assert info["name"].startswith("Construction of New Domestic Terminal")
    assert info["agency"] == "Airport Authority of India [AAI]"
    assert info["paimana_code"] == "701121" and info["ocms_code"] == "N04000103"


def test_table_rows_with_sections():
    header = ["Sl.No", "Project Name\n(Agency)\n(Project Code)", "State", "Date of Approval\n(Start Date)",
              "Orignal/Target DoC\n(Revised DoC)", "Orignal Cost\nRevised Cost", "Cumulative\nExpenditure", "Physical Progress\n(%)"]
    rows = [header, ["", "Ministry of Civil Aviation", None, None, None, None, None, None],
            ["", "Aviation & Aviation Infrastructure", None, None, None, None, None, None],
            ["1", "Terminal Building\n(AAI)\n(612786)\n(N04000106) (-)", "Andhra Pradesh", "03/2023\n(01/2024)",
             "01/2026\n(07/2026)", "265.91\n(300.5)", "129.07", "65"]]
    out = parse_table(rows, {}, completed=False)
    assert len(out) == 1
    r = out[0]
    assert (r["ministry"], r["sector"], r["state"]) == ("Ministry of Civil Aviation", "Aviation & Aviation Infrastructure", "Andhra Pradesh")
    assert (r["start_date"], r["original_completion"], r["revised_completion"]) == ("2024-01", "2026-01", "2026-07")
    assert (r["original_cost_cr"], r["revised_cost_cr"], r["physical_progress_pct"]) == (265.91, 300.5, 65.0)


def test_ids_link_across_eras():
    df = pd.DataFrame({
        "paimana_code": ["111", None, "222", "333", None],
        "ocms_code": ["N1", "N1", "N2", "N2", "N3"],  # N2 was split into two PAIMANA projects
        "report_month": ["2026-01", "2024-06", "2026-01", "2026-01", "2024-06"],
        "ministry": ["M", None, "M", "M", None], "sector": ["S", "OLD", "S", "S", "OLD"],
    })
    df["project_id"] = link_project_ids(df)
    assert list(df["project_id"]) == ["PM-111", "PM-111", "PM-222", "PM-333", "OCMS-N3"]
    h = harmonise(df)
    assert h.loc[4, "ministry"] == "M" and h.loc[4, "sector"] == "S"


@pytest.mark.skipif(not APRIL_2026.exists(), reason="April 2026 Flash Report not in data/reports")
def test_april_2026_matches_official_totals():
    from prism.data.pdf_import import extract

    d = extract(APRIL_2026)
    o = d[d["status"] == "Ongoing"]
    assert len(o) == 1981  # problem statement: 1,981 ongoing projects
    assert round(o["original_cost_cr"].sum() / 1e5, 2) == 37.13  # lakh crore
    assert round(o["revised_cost_cr"].sum() / 1e5, 2) == 42.78
    assert round(o["cumulative_expenditure_cr"].sum() / 1e5, 2) == 20.36
    assert o["ministry"].nunique() == 17 and o["sector"].nunique() == 22


def test_revised_cost_as_plain_second_line():
    header = ["Sl.No", "Project Name (Agency) (Project Code)", "State", "Date of Approval\n(Start Date)",
              "Orignal/Target\nDoC\n(Revised DoC)", "Orignal Cost\nRevised Cost", "Cumulative\nExpenditure", "Physical Progress\n(%)"]
    rows = [header, ["1", "Road\n(NHIDCL)\n(618301)", "Manipur", "09/2020\n(02/2025)", "08/2026\n(12/2026)", "228.97\n0.00", "143.26", "48.36"],
            ["2", "Bridge\n(NHIDCL)\n(618302)", "Manipur", "09/2020\n(02/2025)", "08/2026\n(12/2026)", "100.00\n150.50", "10", "5"]]
    out = parse_table(rows, {}, completed=False)
    assert out[0]["revised_cost_cr"] is None and out[1]["revised_cost_cr"] == 150.5  # 0.00 = not reported
