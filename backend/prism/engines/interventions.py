"""Closed-loop intervention intelligence.

Administrative actions are recorded against a project (historical actions are
imported from the OCMS log; new ones come from the Decision Workspace). For each
action PRISM monitors what happened next -- composite risk and progress velocity
3 and 6 months later -- and compares it with comparable situations where no
action was taken (projects with a bottleneck unresolved for >= 3 months). This
is observational evidence to support review, not a causal estimate.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    intervention_month TEXT NOT NULL,
    action_type TEXT NOT NULL,
    description TEXT NOT NULL,
    authority TEXT,
    source TEXT NOT NULL DEFAULT 'user',
    baseline_risk REAL,
    created_at TEXT NOT NULL
);
"""

ACTION_TYPES = {
    "pmg_review": "PRAGATI / PMG review",
    "funds_released": "Funds released",
    "state_coordination": "State coordination for land / RoW",
    "contractor_action": "Contractor action / re-tendering",
    "clearance_expedited": "Clearance expedited",
    "site_inspection": "Site inspection",
    "other": "Other",
}


class InterventionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.executescript(SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def seed_historical(self, hist: pd.DataFrame) -> None:
        with closing(self._conn()) as c:
            if c.execute("SELECT COUNT(*) FROM interventions WHERE source='historical'").fetchone()[0]:
                return
            now = datetime.utcnow().isoformat(timespec="seconds")
            c.executemany(
                "INSERT INTO interventions (project_id, intervention_month, action_type, description, authority, source, created_at)"
                " VALUES (?,?,?,?,?, 'historical', ?)",
                [(r.project_id, pd.Timestamp(r.intervention_month).strftime("%Y-%m"), r.action_type, r.description,
                  r.authority, now) for r in hist.itertuples(index=False)])
            c.commit()

    def add(self, project_id: str, month: str, action_type: str, description: str, authority: str | None,
            baseline_risk: float | None) -> dict:
        with closing(self._conn()) as c:
            cur = c.execute(
                "INSERT INTO interventions (project_id, intervention_month, action_type, description, authority, source,"
                " baseline_risk, created_at) VALUES (?,?,?,?,?, 'user', ?, ?)",
                (project_id, month, action_type, description, authority, baseline_risk,
                 datetime.utcnow().isoformat(timespec="seconds")))
            c.commit()
            return dict(c.execute("SELECT * FROM interventions WHERE id=?", (cur.lastrowid,)).fetchone())

    def list(self, project_id: str | None = None) -> pd.DataFrame:
        q, args = "SELECT * FROM interventions", ()
        if project_id:
            q, args = q + " WHERE project_id=?", (project_id,)
        with closing(self._conn()) as c:
            return pd.read_sql_query(q + " ORDER BY intervention_month DESC, id DESC", c, params=args)

    def delete(self, iid: int) -> bool:
        with closing(self._conn()) as c:
            n = c.execute("DELETE FROM interventions WHERE id=? AND source='user'", (iid,)).rowcount
            c.commit()
            return n > 0


def control_baseline(panel: pd.DataFrame, iv: pd.DataFrame) -> dict:
    """Average 6-month change in risk / velocity when a bottleneck persisted >= 3 months and no action was logged."""
    p = panel[["project_id", "report_month", "risk_composite", "progress", "velocity_6m", "bottleneck_streak"]].copy()
    g = p.groupby("project_id", sort=False)
    p["risk_6"] = g["risk_composite"].shift(-6)
    p["prog_6"] = g["progress"].shift(-6)
    touched = set(zip(iv["project_id"], iv["intervention_month"]))
    months = p["report_month"].dt.strftime("%Y-%m")
    near = pd.Series([(a, b) in touched for a, b in zip(p["project_id"], months)], index=p.index)
    near = near.groupby(p["project_id"]).transform(lambda s: s.rolling(13, center=True, min_periods=1).max()).astype(bool)
    ctl = p[(p["bottleneck_streak"] >= 3) & ~near & p["risk_6"].notna() & (p["progress"] < 95)]
    basis = "projects with a bottleneck unresolved for 3+ months and no recorded action"
    if len(ctl) < 50:  # e.g. sources without remarks: compare with all comparable ongoing project-months
        ctl = p[~near & p["risk_6"].notna() & (p["progress"] < 95)]
        basis = "all ongoing project-months without a recorded action"
    return {"n": int(len(ctl)), "basis": basis,
            "delta_risk_6m": round(float((ctl["risk_6"] - ctl["risk_composite"]).mean()), 2),
            "velocity_after_6m": round(float(((ctl["prog_6"] - ctl["progress"]) / 6).mean()), 3),
            "velocity_before": round(float(ctl["velocity_6m"].mean()), 3)}


def evaluate(iv: pd.DataFrame, panel: pd.DataFrame, control: dict) -> pd.DataFrame:
    if iv.empty:
        return iv.assign(outcome=[])
    p = panel.set_index(["project_id", panel["report_month"].dt.strftime("%Y-%m")]).sort_index()
    rows = []
    for r in iv.itertuples(index=False):
        rec = r._asdict()
        try:
            hist = p.loc[r.project_id]
        except KeyError:
            rows.append({**rec, "outcome": "Unknown project"})
            continue
        months = list(hist.index)
        pos = next((i for i, m in enumerate(months) if m >= r.intervention_month), None)
        if pos is None:
            pos = len(months) - 1
        before = hist.iloc[pos]
        after = len(months) - 1 - pos
        rec.update({"risk_before": round(float(before["risk_composite"]), 1),
                    "velocity_before": round(float(before["velocity_6m"]), 3),
                    "bottleneck_before": before["bottleneck"], "months_observed_after": int(after)})
        for k in (3, 6):
            if after >= k:
                a = hist.iloc[pos + k]
                rec[f"risk_after_{k}m"] = round(float(a["risk_composite"]), 1)
                rec[f"velocity_after_{k}m"] = round(float((a["progress"] - before["progress"]) / k), 3)
            else:
                rec[f"risk_after_{k}m"] = rec[f"velocity_after_{k}m"] = None
        window = hist.iloc[pos + 1: pos + 7]
        rec["bottleneck_resolved_6m"] = bool((window["bottleneck"] == "none").any()) if len(window) else None
        ref = rec["risk_after_6m"] if rec["risk_after_6m"] is not None else rec["risk_after_3m"]
        if ref is None:
            rec["outcome"] = "Pending (awaiting post-action data)"
            rec["delta_risk"] = rec["excess_vs_control"] = None
        else:
            d = ref - rec["risk_before"]
            # compare against what typically happens without an action over the same window
            ctl = control["delta_risk_6m"] * (1.0 if rec["risk_after_6m"] is not None else 0.5)
            adj = d - ctl
            rec["delta_risk"] = round(d, 1)
            rec["excess_vs_control"] = round(adj, 1)
            v_after = rec["velocity_after_6m"] if rec["velocity_after_6m"] is not None else rec["velocity_after_3m"]
            v_gain = v_after / max(rec["velocity_before"], 0.2)
            ctl_gain = control["velocity_after_6m"] / max(control["velocity_before"], 0.2)
            if adj <= -5 or v_gain >= 1.25 * ctl_gain:
                rec["outcome"] = "Improved"
            elif adj >= 5 or v_gain <= 0.6 * ctl_gain:
                rec["outcome"] = "Worsened"
            else:
                rec["outcome"] = "No material change"
        rows.append(rec)
    return pd.DataFrame(rows)


def effectiveness(evaluated: pd.DataFrame, control: dict) -> list[dict]:
    done = evaluated[evaluated["outcome"].isin(["Improved", "Worsened", "No material change"])]
    out = []
    for a, g in done.groupby("action_type"):
        out.append({"action_type": a, "label": ACTION_TYPES.get(a, a), "n": int(len(g)),
                    "improved_pct": round(float((g["outcome"] == "Improved").mean() * 100), 1),
                    "worsened_pct": round(float((g["outcome"] == "Worsened").mean() * 100), 1),
                    "mean_delta_risk": round(float(g["delta_risk"].mean()), 2),
                    "mean_excess_vs_control": round(float(g["excess_vs_control"].astype(float).mean()), 2)})
    return sorted(out, key=lambda r: -r["improved_pct"])
