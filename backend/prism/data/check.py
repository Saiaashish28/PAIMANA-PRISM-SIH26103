"""Check a data folder without training: ``python -m prism.data.check [folder]``.

Reports what PRISM understood from the files (projects, months, columns, cleaning notes)
and whether there is enough history for every early-warning model.
"""
from __future__ import annotations

import sys
from pathlib import Path

from prism.config import settings


def main() -> int:
    from prism.engines.canonical import build_canonical, load_raw, monthly_files
    from prism.engines.features import build_features
    from prism.engines.trust import clean_and_flag
    from prism.pipeline import check_history

    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.real_dir
    if not folder.is_dir() or not monthly_files(folder):
        print(f"No data files found in {folder}. Put .csv/.xlsx exports there (see data/real/README.md).")
        return 1
    print(f"Reading {folder}")
    try:
        raw = load_raw(folder)
    except ValueError as e:
        print(f"PROBLEM: {e}")
        return 1
    m, mo = raw["master"], raw["monthly"]
    print(f"  files:     {', '.join(raw['files'])}")
    print(f"  projects:  {len(m)}  ({m['ministry'].nunique()} ministries, {m['sector'].nunique()} sectors)")
    print(f"  months:    {mo['report_month'].nunique()}  ({mo['report_month'].min():%b %Y} to {mo['report_month'].max():%b %Y})")
    print(f"  rows:      {len(mo)} project-months")
    for c in ("physical_progress_pct", "cumulative_expenditure_cr", "revised_cost_cr", "remarks"):
        print(f"  missing {c}: {mo[c].isna().mean() * 100:.1f}%")
    for n in raw["notes"]:
        print(f"  note: {n}")
    feats = build_features(clean_and_flag(build_canonical(raw)))
    try:
        check_history(feats)
    except ValueError as e:
        print(f"NOT READY: {e}")
        return 2
    print("READY: enough history to train every model. Run `python -m prism --force` or restart the API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
