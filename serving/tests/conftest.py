"""Test fixtures: point env at the bundled sample artifacts, disable live network.

Weather fetch is disabled (``WEATHER_ENABLED=false``) so /api/predict exercises
the climatological-fallback path deterministically and never touches the network.
Valkey is left disabled (no ``VALKEY_HOST``) so /api/live/positions falls back to
the bundled sample positions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "data" / "sample"


@pytest.fixture(scope="session", autouse=True)
def _env():
    os.environ["DUCKDB_PATH"] = str(SAMPLE / "gold.duckdb")
    os.environ["MODEL_PATH"] = str(SAMPLE / "model.lgb")
    os.environ["SAMPLE_DIR"] = str(SAMPLE)
    os.environ["DATA_VERSION"] = "test-sample"
    os.environ["WEATHER_ENABLED"] = "false"   # force weather defaults (offline)
    os.environ.pop("VALKEY_HOST", None)        # force sample positions
    os.environ["VALKEY_ENABLED"] = "false"
    # No S3 -> bundled sample artifacts.
    for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        os.environ.pop(k, None)
    yield


@pytest.fixture(scope="session")
def client(_env):
    from fastapi.testclient import TestClient

    from flight_serving.app import app

    with TestClient(app) as c:  # triggers lifespan (loads model + gold)
        yield c
