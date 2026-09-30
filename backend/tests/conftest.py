import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="prism-test-"))
os.environ["PRISM_DATA_DIR"] = str(_TMP)
os.environ["PRISM_LLM_ENABLED"] = "0"
os.environ["PRISM_WATCH_INTERVAL"] = "0"


@pytest.fixture(scope="session")
def raw_dir():
    from prism.data.generator import generate

    d = _TMP / "raw"
    generate(n_projects=140, seed=7, out_dir=d)
    return d


@pytest.fixture(scope="session")
def state(raw_dir):
    from prism.pipeline import build_state

    return build_state(raw_dir)
