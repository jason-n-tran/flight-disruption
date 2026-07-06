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


@dataclass(frozen=True)
class Settings:
    """Resolved ingestion settings.

    ``ssl_verify`` defaults to True (production has no corporate proxy). On this
    dev machine the corporate SSL proxy breaks verification, so set
    ``INGEST_SSL_VERIFY=false`` (the documented escape hatch) for live runs.
    """

    lake_root: str
    data_dir: Path
    ssl_verify: bool
    http_timeout: float
    request_pause_sec: float
    max_retries: int
    user_agent: str
    opensky_client_id: str | None
    opensky_client_secret: str | None
    # Defaulted so callers constructing Settings positionally (incl. the
    # streaming component reusing this dataclass) keep working.
    weather_pause_sec: float = 3.0
    max_backoff_sec: float = 60.0
    # Open-Meteo free tier = 10,000 weighted calls/day. A 4-year x 5-var archive
    # call costs ~days/14 ≈ 104 units, so ~90 airports fit safely in one day.
    # Weather ingest stops cleanly at this budget and resumes next run (the
    # backfill is resumable — written airports are skipped).
    weather_daily_budget: int = 90
    # Circuit breaker: if this many airports 429 back-to-back (daily quota
    # already spent by an earlier run), abort the weather stage fast instead of
    # grinding through every airport x retries.
    weather_quota_abort_after: int = 3

    @property
    def paths(self) -> Paths:
        return paths(self.lake_root)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Build :class:`Settings` from the current environment."""
    lake_root = os.environ.get("LAKE_ROOT", os.path.abspath("./data/lake"))
    data_dir = Path(os.environ.get("INGEST_DATA_DIR", os.path.abspath("./data/raw")))
    return Settings(
        lake_root=lake_root,
        data_dir=data_dir,
        ssl_verify=_env_bool("INGEST_SSL_VERIFY", True),
        http_timeout=_env_float("INGEST_HTTP_TIMEOUT", 120.0),
        request_pause_sec=_env_float("INGEST_REQUEST_PAUSE_SEC", 0.5),
        # Open-Meteo weights calls by (vars x days); a heavy 4yr x 5var pull
        # needs a longer inter-call pause to stay under the free per-minute limit.
        weather_pause_sec=_env_float("INGEST_WEATHER_PAUSE_SEC", 3.0),
        max_retries=int(os.environ.get("INGEST_MAX_RETRIES", "5")),
        # Cap exponential backoff; raised so a 429 with no Retry-After still
        # waits meaningfully instead of hammering. Retry-After header wins.
        max_backoff_sec=_env_float("INGEST_MAX_BACKOFF_SEC", 60.0),
        weather_daily_budget=int(os.environ.get("INGEST_WEATHER_DAILY_BUDGET", "90")),
        weather_quota_abort_after=int(
            os.environ.get("INGEST_WEATHER_QUOTA_ABORT_AFTER", "3")
        ),
        user_agent=os.environ.get(
            "INGEST_USER_AGENT",
            "flight-disruption-platform/0.1 (portfolio; ingestion)",
        ),
        opensky_client_id=os.environ.get("OPENSKY_CLIENT_ID") or None,
        opensky_client_secret=os.environ.get("OPENSKY_CLIENT_SECRET") or None,
    )


# Source URLs (constants — empirically verified, see README).
BTS_URL_TEMPLATE = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPENFLIGHTS_AIRPORTS_URL = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
