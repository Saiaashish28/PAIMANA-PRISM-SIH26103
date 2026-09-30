"""Synthetic PAIMANA/OCMS data generator.

The real PAIMANA portal has no public bulk export, so PRISM ships a generator
that produces a statistically realistic panel mirroring the Common Upload Form
(CUF): identity, ministry/sector/state, sanctioned vs revised cost, cumulative
expenditure, physical progress, original vs revised completion and free-text
remarks. Projects are simulated month by month, so:

* bottlenecks appear in the remarks *before* cost and schedule revisions are
  sanctioned (the early-warning signal PRISM is meant to pick up);
* contractor credit, land-acquisition friction, weather/geopolitical exposure
  and a construction cost index (non-CUF variables) raise the hazard of events
  without being visible in CUF fields -- this is what the CUF-sufficiency
  analysis measures;
* a log of historical administrative interventions is produced, with some of
  them actually improving execution afterwards, so the closed-loop monitor has
  something real to measure;
* data-quality defects (missing values, contradictions, stale reporting,
  outliers) are injected so the Data Trust engine has work to do.

Swapping in real exports only requires matching the three CSV schemas.

Run: ``python -m prism.data.generator [--projects N]``
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from prism.config import settings

CURRENT_MONTH = date(2026, 4, 1)
HISTORY_START = date(2010, 1, 1)

SECTOR_BY_MINISTRY = {
    "Road Transport & Highways": ["National Highways", "Expressways", "Bridges & Tunnels"],
    "Railways": ["New Rail Lines", "Gauge Conversion", "Rail Electrification", "Doubling"],
    "Power": ["Thermal Power", "Transmission", "Hydro Power"],
    "Petroleum & Natural Gas": ["Pipelines", "Refineries"],
    "Coal": ["Coal Mining"],
    "Steel": ["Steel Plants"],
    "Mines": ["Mineral Exploration"],
    "Ports, Shipping & Waterways": ["Ports", "Inland Waterways"],
    "Civil Aviation": ["Airports"],
    "Jal Shakti": ["Irrigation", "Water Supply"],
    "Housing & Urban Affairs": ["Metro Rail", "Urban Infrastructure"],
    "New & Renewable Energy": ["Solar Parks", "Wind Power"],
    "Telecommunications": ["Telecom Networks"],
    "Atomic Energy": ["Nuclear Power"],
    "Chemicals & Fertilizers": ["Fertilizer Plants"],
    "Health & Family Welfare": ["Hospitals (AIIMS)"],
    "Education": ["Higher Education Campuses"],
}
MINISTRY_WEIGHTS = {
    "Road Transport & Highways": 0.24, "Railways": 0.2, "Power": 0.07, "Petroleum & Natural Gas": 0.09,
    "Coal": 0.05, "Steel": 0.02, "Mines": 0.01, "Ports, Shipping & Waterways": 0.03, "Civil Aviation": 0.03,
    "Jal Shakti": 0.04, "Housing & Urban Affairs": 0.06, "New & Renewable Energy": 0.04,
    "Telecommunications": 0.03, "Atomic Energy": 0.02, "Chemicals & Fertilizers": 0.02,
    "Health & Family Welfare": 0.03, "Education": 0.02,
}
# Sector-level structural risk (e.g. hydro and new lines are notoriously harder).
SECTOR_RISK = {
    "Hydro Power": 0.25, "New Rail Lines": 0.2, "Metro Rail": 0.12, "Irrigation": 0.2, "Nuclear Power": 0.22,
    "Bridges & Tunnels": 0.15, "Refineries": 0.08, "Airports": 0.05, "Solar Parks": -0.1, "Wind Power": -0.05,
    "Telecom Networks": -0.05, "Transmission": 0.05, "Gauge Conversion": 0.1, "Hospitals (AIIMS)": 0.1,
}

# State centroids (lat, lon) for the geographic view.
STATES = {
    "Andhra Pradesh": (15.9, 79.7), "Arunachal Pradesh": (28.2, 94.7), "Assam": (26.2, 92.9),
    "Bihar": (25.1, 85.3), "Chhattisgarh": (21.3, 81.9), "Gujarat": (22.3, 71.2), "Haryana": (29.1, 76.1),
    "Himachal Pradesh": (31.9, 77.1), "Jammu & Kashmir": (33.7, 75.1), "Jharkhand": (23.6, 85.3),
    "Karnataka": (15.3, 75.7), "Kerala": (10.5, 76.3), "Madhya Pradesh": (23.5, 78.6),
    "Maharashtra": (19.7, 75.7), "Odisha": (20.9, 84.8), "Punjab": (31.1, 75.3), "Rajasthan": (27.0, 74.2),
    "Tamil Nadu": (11.1, 78.7), "Telangana": (18.1, 79.0), "Uttar Pradesh": (26.8, 80.9),
    "Uttarakhand": (30.1, 79.0), "West Bengal": (22.9, 87.9), "Delhi": (28.6, 77.2),
}
# Terrain / land-acquisition difficulty per state (drives non-CUF friction score).
HARD_TERRAIN = {"Arunachal Pradesh", "Himachal Pradesh", "Jammu & Kashmir", "Uttarakhand", "Assam"}
DENSE_LAND = {"Kerala", "West Bengal", "Bihar", "Uttar Pradesh", "Delhi", "Maharashtra"}

BOTTLENECKS = {
    "land_acquisition": [
        "Land acquisition pending for {k} km stretch; compensation disputes with landowners.",
        "Right-of-Way handover by State Government delayed for balance land.",
        "Delay in land acquisition under RFCTLARR Act; award not yet declared for {k} villages.",
    ],
    "forest_clearance": [
        "Stage-II forest clearance awaited from MoEF&CC.",
        "Wildlife clearance pending before Standing Committee of NBWL.",
        "Environmental clearance conditions under review; tree felling permission awaited.",
    ],
    "contractor_issues": [
        "Slow progress by contractor due to poor financial health; mobilisation inadequate.",
        "Contractor facing liquidity crunch; sub-contractor payments pending.",
        "Termination notice issued to contractor for non-performance; re-tendering under consideration.",
    ],
    "funding_delay": [
        "Delay in release of funds; budgetary allocation inadequate for current year.",
        "Cash flow constraints due to delay in reimbursement of bills.",
    ],
    "utility_shifting": [
        "Shifting of utilities (HT lines, water mains) held up by utility-owning agencies.",
        "Utility relocation by State DISCOM pending, obstructing work front.",
    ],
    "litigation": [
        "Work stalled due to court stay order; matter sub-judice.",
        "Arbitration proceedings ongoing with contractor over claims.",
    ],
    "geology_weather": [
        "Unforeseen geological conditions encountered; design revision required.",
        "Work suspended due to heavy monsoon rains and flooding at site.",
        "Slope failure / landslide at site; restoration work in progress.",
    ],
    "design_scope": [
        "Change in scope and design revision requested by user agency.",
        "Additional works added to scope; revised estimate under preparation.",
    ],
    "law_and_order": [
        "Law and order problem in project area; work disrupted by local agitation.",
    ],
}
NO_ISSUE_REMARKS = [
    "Work progressing as per schedule.",
    "Progress satisfactory; no major constraint reported.",
    "Work in progress on all fronts.",
    "Project on track as per revised schedule.",
]
INTERVENTION_TYPES = [
    ("pmg_review", "Taken up in PRAGATI / PMG review meeting", 0.65),
    ("funds_released", "Additional funds released by Ministry of Finance", 0.7),
    ("state_coordination", "Chief Secretary level coordination meeting for land/RoW", 0.6),
    ("contractor_action", "Contractor replaced / risk-and-cost re-tendering initiated", 0.55),
    ("clearance_expedited", "Clearance expedited by inter-ministerial committee", 0.6),
    ("site_inspection", "Targeted site inspection by IPMD team", 0.4),
]


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _macro_index(rng: np.random.Generator) -> pd.DataFrame:
    """Monthly construction-material cost index (non-CUF macro variable)."""
    months = pd.date_range(HISTORY_START, CURRENT_MONTH, freq="MS")
    drift = np.full(len(months), 0.004)
    # commodity shock 2021-22 and a milder one 2011-12
    drift[(months >= "2021-03-01") & (months <= "2022-09-01")] += 0.012
    drift[(months >= "2011-01-01") & (months <= "2012-06-01")] += 0.006
    idx = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, len(months))))
    df = pd.DataFrame({"month": months, "construction_cost_index": idx.round(2)})
    df["cci_yoy_pct"] = (df["construction_cost_index"].pct_change(12) * 100).round(2).fillna(4.8)
    return df


def _contractor_pool(rng: np.random.Generator, n: int = 140) -> pd.DataFrame:
    quality = rng.beta(4, 2, n)  # hidden execution quality
    return pd.DataFrame({
        "contractor_name": [f"{a} {b}" for a, b in zip(
            rng.choice(["Bharat", "Shree", "Apex", "Hindustan", "Deccan", "Ganga", "Sahyadri", "Coromandel",
                        "Vindhya", "Narmada", "Kaveri", "Aravali", "Konark", "Indus", "Garuda"], n),
            [f"Infra-{i:03d}" for i in range(n)])],
        "quality": quality,
        "contractor_credit_score": np.clip(35 + 60 * quality + rng.normal(0, 7, n), 5, 100).round(1),
    })


def _simulate_project(pid: int, rng: np.random.Generator, contractors: pd.DataFrame, macro: pd.DataFrame):
    ministry = rng.choice(list(MINISTRY_WEIGHTS), p=np.array(list(MINISTRY_WEIGHTS.values())) / sum(MINISTRY_WEIGHTS.values()))
    sector = rng.choice(SECTOR_BY_MINISTRY[ministry])
    state = rng.choice(list(STATES))
    lat, lon = STATES[state]
    contractor = contractors.iloc[int(rng.integers(len(contractors)))]

    # Mega (>=1000 Cr) and major (150-1000 Cr) projects.
    original_cost = float(np.round(np.clip(150 + np.exp(rng.normal(6.2, 1.1)), 150, 45000), 1))
    planned_months = int(np.clip(rng.normal(22 + 9 * np.log10(original_cost / 150 + 1) * 3, 9), 12, 108))
    # Start dates spread across the OCMS -> PAIMANA era, skewed to recent years.
    span = _months_between(HISTORY_START, CURRENT_MONTH) - 4
    start = _add_months(HISTORY_START, int(span * rng.beta(2.2, 1.0)))

    land_friction = float(np.clip(rng.normal(30 + 25 * (state in DENSE_LAND) + 10 * (sector in {
        "National Highways", "Expressways", "New Rail Lines", "Metro Rail", "Irrigation", "Doubling"}), 14), 0, 100))
    weather_geo = float(np.clip(rng.normal(22 + 35 * (state in HARD_TERRAIN) + 8 * (sector in {
        "Hydro Power", "Bridges & Tunnels", "Ports"}), 12), 0, 100))
    credit = float(contractor["contractor_credit_score"])

    latent = (0.35 + SECTOR_RISK.get(sector, 0.0) + 0.35 * (1 - contractor["quality"])
              + 0.25 * land_friction / 100 + 0.2 * weather_geo / 100 + rng.normal(0, 0.12))
    latent = float(np.clip(latent, 0.02, 1.2))

    bn_weights = {
        "land_acquisition": 0.5 + 3 * land_friction / 100, "forest_clearance": 0.6 + (weather_geo > 45),
        "contractor_issues": 0.4 + 3 * (1 - credit / 100), "funding_delay": 0.6,
        "utility_shifting": 0.5 + (sector in {"Metro Rail", "National Highways", "Expressways", "Urban Infrastructure"}),
        "litigation": 0.35, "geology_weather": 0.3 + 2.2 * weather_geo / 100, "design_scope": 0.5,
        "law_and_order": 0.1 + 0.6 * (state in {"Jammu & Kashmir", "Chhattisgarh", "Jharkhand"}),
    }
    bn_keys = list(bn_weights)
    bn_p = np.array(list(bn_weights.values()))
    bn_p = bn_p / bn_p.sum()

    macro_lookup = macro.set_index("month")["cci_yoy_pct"]

    progress = 0.0
    cost = original_cost
    expenditure = 0.0
    orig_completion = _add_months(start, planned_months)
    revised_completion = orig_completion
    bottleneck = "none"
    bn_age = 0
    boost_until = -1
    boost = 1.0
    rows, interventions = [], []
    # The *true* cost of the works drifts away from the sanctioned cost; expenditure follows the
    # true cost, so financial progress running ahead of physical progress precedes a revision.
    true_cost = original_cost * max(0.92, rng.normal(1.0 + 0.18 * latent, 0.06))
    n_months = _months_between(start, CURRENT_MONTH) + 1

    for t in range(n_months):
        month = _add_months(start, t)
        # --- bottleneck dynamics -------------------------------------------------------
        if bottleneck == "none":
            onset = 0.015 + 0.075 * latent
            if rng.random() < onset:
                bottleneck = str(rng.choice(bn_keys, p=bn_p))
                bn_age = 0
        else:
            bn_age += 1
            resolve = 0.12 + 0.12 * (1 - latent) + (0.15 if t <= boost_until else 0.0)
            if rng.random() < resolve:
                bottleneck = "none"
                bn_age = 0

        # --- progress ------------------------------------------------------------------
        months_left = max(_months_between(month, revised_completion), 1)
        # capacity-driven work rate following an S-curve over the planned programme
        base_rate = 100 / planned_months / 1.13 * (0.6 + 3.2 * (progress / 100) * (1 - progress / 100))
        efficiency = rng.normal(1.15 - 0.5 * latent, 0.12)
        if bottleneck != "none":
            efficiency *= {"litigation": 0.15, "land_acquisition": 0.45, "forest_clearance": 0.4,
                           "contractor_issues": 0.35, "law_and_order": 0.3}.get(bottleneck, 0.6)
        if month.month in (7, 8, 9):  # monsoon
            efficiency *= 1 - 0.35 * weather_geo / 100
        if t <= boost_until:
            efficiency *= boost
        # ramp-up in the first months, slow tail near completion (S-curve shape)
        ramp = min(1.0, (t + 1) / 6)
        step = max(0.0, base_rate * np.clip(efficiency, 0, 1.6) * ramp)
        progress = float(min(100.0, progress + step))

        # --- schedule revisions ---------------------------------------------------------
        if progress < 100:
            proj_left = (100 - progress) / max(step, 0.05)
            gap = proj_left - months_left
            hazard = 0.0
            if gap > 4 and bottleneck != "none" and bn_age >= 2:
                hazard = 0.18
            if months_left <= 1:
                hazard = 0.9
            if rng.random() < hazard:
                slip = int(np.clip(np.ceil(min(gap, 36) * rng.uniform(0.4, 0.9)), 3, 36))
                revised_completion = _add_months(revised_completion, slip)

        # --- cost revisions -------------------------------------------------------------
        cci = float(macro_lookup.get(pd.Timestamp(month), 5.0))
        escalation = 0.002 * latent + 0.002 * max(cci - 6, 0)
        if bottleneck in {"design_scope", "geology_weather", "land_acquisition"} and bn_age >= 2:
            escalation += 0.05
        if progress < 95 and rng.random() < escalation:
            true_cost *= 1 + rng.uniform(0.03, 0.12) * (0.7 + latent)
        headroom = expenditure / cost  # funds nearly exhausted while work remains -> revised estimate
        revise = 0.0
        if headroom > 0.88 and progress < 95:
            revise = 0.3
        elif true_cost > cost * 1.12:
            revise = 0.04
        if progress < 97 and rng.random() < revise:
            cost = round(max(cost * 1.02, true_cost * rng.uniform(1.0, 1.06)), 2)

        # --- expenditure ----------------------------------------------------------------
        target_exp = true_cost * progress / 100 * (1 + 0.04 * np.sin(t / 5))
        expenditure = float(max(expenditure, min(target_exp, cost)))

        remarks = (rng.choice(BOTTLENECKS[bottleneck]).format(k=int(rng.integers(2, 40)))
                   if bottleneck != "none" else rng.choice(NO_ISSUE_REMARKS))
        status = "Completed" if progress >= 100 else "Ongoing"
        rows.append(dict(
            project_id=f"PRJ-{pid:05d}", report_month=month.isoformat(),
            physical_progress_pct=round(progress, 2), cumulative_expenditure_cr=round(expenditure, 2),
            revised_cost_cr=round(cost, 2), revised_completion=revised_completion.isoformat(),
            status=status, remarks=remarks, bottleneck_category=bottleneck,
        ))

        # --- historical administrative interventions -----------------------------------
        if (status == "Ongoing" and bottleneck != "none" and bn_age >= 3 and t > boost_until
                and rng.random() < 0.08 * (1 + latent)):
            kind, desc, success = INTERVENTION_TYPES[int(rng.integers(len(INTERVENTION_TYPES)))]
            worked = rng.random() < success
            if worked:
                boost_until = t + int(rng.integers(4, 9))
                boost = rng.uniform(1.25, 1.7)
                if rng.random() < 0.6:
                    bottleneck, bn_age = "none", 0
            interventions.append(dict(
                project_id=f"PRJ-{pid:05d}", intervention_month=month.isoformat(), action_type=kind,
                description=desc, authority=rng.choice(["IPMD", "Line Ministry", "Cabinet Secretariat", "PMG"]),
            ))
        if status == "Completed":
            break

    master = dict(
        project_id=f"PRJ-{pid:05d}",
        project_name=f"{sector} – {state} Package {pid}",
        ministry=ministry, sector=sector, state=state,
        latitude=round(lat + rng.normal(0, 0.9), 4), longitude=round(lon + rng.normal(0, 0.9), 4),
        implementing_agency=f"{ministry.split()[0]} PSU {int(rng.integers(1, 12))}",
        contractor_name=contractor["contractor_name"],
        start_date=start.isoformat(), original_completion=orig_completion.isoformat(),
        original_cost_cr=original_cost,
        # --- non-CUF supplementary variables (ps.md 4.3) ---
        contractor_credit_score=round(credit, 1),
        land_acquisition_friction_score=round(land_friction, 1),
        weather_geopolitical_risk_index=round(weather_geo, 1),
    )
    return master, rows, interventions


def _inject_quality_issues(monthly: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    m = monthly.copy()
    n = len(m)
    for col, frac in [("cumulative_expenditure_cr", 0.05), ("physical_progress_pct", 0.04), ("remarks", 0.06)]:
        idx = rng.choice(n, int(n * frac), replace=False)
        m.loc[m.index[idx], col] = np.nan
    # contradictions: expenditure > sanctioned cost
    idx = rng.choice(n, int(n * 0.008), replace=False)
    m.loc[m.index[idx], "cumulative_expenditure_cr"] = m.loc[m.index[idx], "revised_cost_cr"] * rng.uniform(1.1, 1.5, len(idx))
    # contradictions: progress regressing (data-entry error)
    idx = rng.choice(n, int(n * 0.01), replace=False)
    m.loc[m.index[idx], "physical_progress_pct"] = (m.loc[m.index[idx], "physical_progress_pct"] * rng.uniform(0.4, 0.85, len(idx))).round(2)
    # outliers: fat-fingered progress jumps (e.g. 4.5 -> 45)
    idx = rng.choice(n, int(n * 0.004), replace=False)
    m.loc[m.index[idx], "physical_progress_pct"] = np.minimum(m.loc[m.index[idx], "physical_progress_pct"] * 10, 100).round(2)
    # staleness: drop the most recent 2-6 months for ~8% of ongoing projects
    last = m.groupby("project_id").tail(1)
    ongoing = last.loc[last["status"] == "Ongoing", "project_id"].to_numpy()
    stale = rng.choice(ongoing, max(1, int(len(ongoing) * 0.08)), replace=False)
    drop = []
    for pid in stale:
        idxs = m.index[m["project_id"] == pid]
        drop.extend(idxs[-int(rng.integers(2, 7)):].tolist())
    return m.drop(index=drop).reset_index(drop=True)


def generate(n_projects: int = 700, seed: int | None = None, out_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(settings.random_seed if seed is None else seed)
    out_dir = Path(out_dir or settings.raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    macro = _macro_index(rng)
    contractors = _contractor_pool(rng)
    masters, monthly, interventions = [], [], []
    for pid in range(1, n_projects + 1):
        m, rows, iv = _simulate_project(pid, rng, contractors, macro)
        masters.append(m)
        monthly.extend(rows)
        interventions.extend(iv)

    master_df = pd.DataFrame(masters)
    monthly_df = _inject_quality_issues(pd.DataFrame(monthly), rng)
    iv_df = pd.DataFrame(interventions, columns=["project_id", "intervention_month", "action_type", "description", "authority"])
    macro_out = macro.assign(month=macro["month"].dt.date.astype(str))

    master_df.to_csv(out_dir / "project_master.csv", index=False)
    monthly_df.to_csv(out_dir / "monthly_snapshots.csv", index=False)
    iv_df.to_csv(out_dir / "interventions_history.csv", index=False)
    macro_out.to_csv(out_dir / "macro_indicators.csv", index=False)
    return dict(master=master_df, monthly=monthly_df, interventions=iv_df, macro=macro_out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--projects", type=int, default=700)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = generate(args.projects, args.seed, args.out)
    last = out["monthly"].groupby("project_id").tail(1)
    print(f"{len(out['master'])} projects, {len(out['monthly'])} monthly snapshots, "
          f"{len(out['interventions'])} historical interventions; "
          f"{(last['status'] == 'Ongoing').sum()} ongoing / {(last['status'] == 'Completed').sum()} completed")


if __name__ == "__main__":
    main()
