"""Environment-driven configuration for the serving layer.

Every setting reads from an env var with a sensible local-dev default that points
at the bundled sample artifacts (``data/sample/``) so a fresh clone runs offline.

Resolution rules
----------------
* ``MODEL_PATH`` points at ``model.lgb``; the *bundle directory* is its parent
  (the dir holding ``model.lgb`` + ``calibrator.pkl`` + ``feature_metadata.json``).
  ``flight_ml.artifacts.load_bundle`` takes that directory.
* ``DUCKDB_PATH`` is the gold DuckDB file (opened read-only).
* ``SAMPLE_DIR`` is the bundled fallback bundle/positions dir (``data/sample``).
* ``S3_*`` (optional) enables pulling the latest artifacts on startup; when blank
  the bundled sample artifacts are used as-is (see ``artifacts_loader``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _repo_root() -> Path:
    # serving/flight_serving/config.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def _default_sample_dir() -> str:
    env = os.environ.get("SAMPLE_DIR")
    if env:
        return env
    return str(_repo_root() / "data" / "sample")
