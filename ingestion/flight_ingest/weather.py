"""Open-Meteo historical (archive) weather ingestion.

For each airport (lat/lon from the OpenFlights dim) one archive call returns the
full multi-year hourly series. We request exactly ``WEATHER_ARCHIVE_VARS`` —
``visibility`` is NULL on the archive endpoint and is intentionally never asked
for. Output: ``bronze/weather_hourly`` parquet (iata, time, + archive vars).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from flight_contracts import BRONZE_YEARS, WEATHER_ARCHIVE_VARS

from ._http import get_with_retry, make_client
from .config import OPEN_METEO_ARCHIVE_URL, Settings

log = logging.getLogger("flight_ingest.weather")

BRONZE_TABLE = "weather_hourly"
# Cooldown marker written when the daily quota is exhausted. On the next run we
# do ONE cheap probe instead of spamming; if it still 429s we skip cleanly.
_COOLDOWN_FILE = "_weather_quota_cooldown.json"
BTS_BRONZE_TABLE = "bts_ontime"

# Hard guard against the visibility-on-archive trap, regardless of caller input.
_FORBIDDEN_ARCHIVE_VARS = {"visibility"}


def _date_range(years: list[int]) -> tuple[str, str]:
    start = f"{min(years)}-01-01"
    end = f"{max(years)}-12-31"
    return start, end


def build_archive_params(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    """Construct Open-Meteo archive query params for one location.

    Asserts visibility is never requested (training-leakage / null-data guard).
    """
    hourly_vars = list(WEATHER_ARCHIVE_VARS)
    assert not (_FORBIDDEN_ARCHIVE_VARS & set(hourly_vars)), (
        "visibility must never be requested from the archive endpoint"
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(hourly_vars),
        "timezone": "UTC",
    }


def parse_archive_response(iata: str, payload: dict) -> pd.DataFrame:
    """Turn an Open-Meteo archive JSON payload into a tidy per-hour frame."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    data: dict[str, object] = {"iata": iata, "time": times}
    for var in WEATHER_ARCHIVE_VARS:
        data[var] = hourly.get(var, [None] * len(times))
    df = pd.DataFrame(data, columns=["iata", "time", *WEATHER_ARCHIVE_VARS])
    if not df.empty:
        # Microsecond precision (NOT the pandas default ns): Spark 3.5 rejects
        # Parquet TIMESTAMP(NANOS) with "Illegal Parquet type INT64
        # (TIMESTAMP(NANOS,true))". us is the widest precision Spark reads.
        df["time"] = (
            pd.to_datetime(df["time"], utc=True).dt.tz_convert("UTC").astype("datetime64[us, UTC]")
        )
    return df


def fetch_airport(
    settings: Settings,
    client,
    iata: str,
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch the full archive series for a single airport."""
    params = build_archive_params(lat, lon, start_date, end_date)
    resp = get_with_retry(
        client,
        OPEN_METEO_ARCHIVE_URL,
        max_retries=settings.max_retries,
        pause=settings.request_pause_sec,
        max_backoff=settings.max_backoff_sec,
        params=params,
    )
    return parse_archive_response(iata, resp.json())
