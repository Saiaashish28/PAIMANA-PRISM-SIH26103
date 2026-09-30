"""Bottleneck extraction from free-text CUF remarks.

Real PAIMANA remarks are unstructured narratives, so PRISM never relies on a
pre-labelled category column. A transparent lexicon classifier maps each remark
to a bottleneck category; it is deterministic, auditable and runs offline. The
LLM layer can refine ambiguous remarks, but the risk models only consume this
deterministic output so that scores are reproducible.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

CATEGORY_LABELS = {
    "land_acquisition": "Land acquisition / Right-of-Way",
    "forest_clearance": "Forest & environmental clearance",
    "contractor_issues": "Contractor performance / capacity",
    "funding_delay": "Funding & cash-flow delay",
    "utility_shifting": "Utility shifting",
    "litigation": "Litigation / arbitration",
    "geology_weather": "Geology, weather & natural events",
    "design_scope": "Design change / scope creep",
    "law_and_order": "Law & order / local agitation",
    "none": "No bottleneck reported",
}

# Ordered: the first matching pattern wins (most specific first).
_LEXICON: list[tuple[str, str]] = [
    ("litigation", r"court|sub-judice|sub judice|stay order|arbitration|litigation|legal dispute"),
    ("forest_clearance", r"forest|wildlife|nbwl|moef|environment(al)? clearance|tree felling|\bec\b"),
    ("land_acquisition", r"land acquisition|right[- ]of[- ]way|\brow\b|rfctlarr|landowner|compensation|acquisition"),
    ("utility_shifting", r"utilit|discom|ht line|water main|pipeline shifting|relocation"),
    ("contractor_issues", r"contractor|mobilis|mobiliz|sub-contractor|termination|non-performance|re-tender|liquidity"),
    ("funding_delay", r"fund|budget|cash flow|reimbursement|allocation|payment"),
    ("geology_weather", r"geolog|monsoon|rain|flood|landslide|slope|cyclone|weather|earthquake"),
    ("design_scope", r"scope|design|revised estimate|additional work"),
    ("law_and_order", r"law and order|agitation|protest|bandh|security|naxal|insurgen"),
]
_COMPILED = [(cat, re.compile(pat, re.IGNORECASE)) for cat, pat in _LEXICON]
_NO_ISSUE = re.compile(r"as per schedule|on track|satisfactory|no (major )?(constraint|impediment|issue)|in progress on all", re.I)


def classify_remark(text) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return "unknown"
    t = str(text)
    if _NO_ISSUE.search(t):
        return "none"
    for cat, rx in _COMPILED:
        if rx.search(t):
            return cat
    return "none"


def classify_series(remarks: pd.Series) -> pd.Series:
    # Remarks repeat heavily month to month -> classify unique strings only.
    uniq = pd.Series(remarks.dropna().unique())
    mapping = dict(zip(uniq, uniq.map(classify_remark)))
    return remarks.map(mapping).fillna("unknown")
