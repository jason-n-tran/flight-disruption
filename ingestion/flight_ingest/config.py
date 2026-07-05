"""Env-driven configuration for the ingestion layer.

Everything is overridable via environment variables (see ``.env.example``).
Nothing here requires a ``.env`` file to be present — sensible defaults keep a
fresh clone runnable, and missing OpenSky creds degrade to anonymous fetches.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from flight_contracts import paths
from flight_contracts.contract import Paths


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)
