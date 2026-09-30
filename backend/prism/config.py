"""Central configuration for PAIMANA PRISM.

Everything tunable lives here and can be overridden through environment
variables (prefixed ``PRISM_``) so the same code runs on a laptop, in Docker,
or inside an air-gapped ministry network.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PRISM_{name}", default)


def normalise_host(host: str) -> str:
    """Accept the forms Ollama users type ("0.0.0.0", "localhost:11434", "http://host") and return a URL."""
    h = (host or "").strip().rstrip("/") or "http://127.0.0.1:11434"
    if "://" not in h:
        h = "http://" + h
    scheme, rest = h.split("://", 1)
    name, _, port = rest.partition(":")
    if name in ("0.0.0.0", "", "*"):
        name = "127.0.0.1"
    return f"{scheme}://{name}:{port or '11434'}"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(REPO_ROOT / "data"))))
    # Ollama (local, air-gapped LLM). Qwen 2.5 3B keeps the footprint laptop-sized.
    ollama_host: str = field(default_factory=lambda: normalise_host(_env("OLLAMA_HOST", "http://127.0.0.1:11434")))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:3b"))
    ollama_timeout_s: float = field(default_factory=lambda: float(_env("OLLAMA_TIMEOUT", "180")))
    llm_enabled: bool = field(default_factory=lambda: _env("LLM_ENABLED", "1") == "1")
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(_env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    )
    random_seed: int = 42
    # "auto": use data/real/ when it contains files, otherwise the synthetic data/raw/.
    # "real" / "synthetic" force one source.
    data_source: str = field(default_factory=lambda: _env("DATA_SOURCE", "auto"))
    # live feed: how often (seconds) data/reports and data/real are checked for new files; 0 disables
    watch_interval_s: float = field(default_factory=lambda: float(_env("WATCH_INTERVAL", "30")))

    @property
    def raw_dir(self) -> Path:
        """Bundled synthetic dataset."""
        return self.data_dir / "raw"

    @property
    def real_dir(self) -> Path:
        """Folder where real PAIMANA/OCMS exports are dropped."""
        return self.data_dir / "real"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "prism.db"


# Early-warning horizons (months) from the proposal: 3, 6 and 12-month warnings.
HORIZONS: tuple[int, ...] = (3, 6, 12)
# The three risk dimensions tracked for every project.
DIMENSIONS: tuple[str, ...] = ("cost", "schedule", "implementation")

# Event definitions used to build early-warning labels (see engines/features.py).
COST_EVENT_PP = 5.0          # cost growth rises by >= 5 percentage points of original cost
SCHEDULE_EVENT_MONTHS = 3    # revised completion slips by >= 3 more months
STALL_RATIO = 0.25           # near-standstill: realised progress < 25% of the planned average pace

# Composite risk (0-100) bands used together with active warnings for Red/Amber/Green.
RAG_RED = 45.0
RAG_AMBER = 20.0

settings = Settings()
