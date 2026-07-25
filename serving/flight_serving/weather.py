"""Serve-time weather forecast fetch with graceful degradation.

For ``/api/predict`` we need the forecast at the origin + dest for the flight's
scheduled departure window. We hit the Open-Meteo **forecast** endpoint and pull
the contract weather vars at the requested ``dep_hour``.

CRITICAL graceful behavior (see component spec + project memory):

* On this dev machine an SSL proxy blocks outbound HTTPS from Python, so the
  fetch is EXPECTED to fail; the demo must work offline.
* If the date is beyond the forecast horizon, or the API is unreachable, or the
  hour is missing, we fall back to **climatological/zero defaults** so
  ``/api/predict`` NEVER fails. We log a note and still return a prediction.

The five contract vars map to Open-Meteo hourly fields::

    origin/dest_temp_2m    <- temperature_2m
    origin/dest_precip     <- precipitation
    origin/dest_wind_speed <- wind_speed_10m
    origin/dest_wind_gusts <- wind_gusts_10m
    origin/dest_snowfall   <- snowfall
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

log = logging.getLogger("flight_serving.weather")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo hourly var -> our contract suffix.
_VAR_MAP = {
    "temperature_2m": "temp_2m",
    "precipitation": "precip",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_gusts",
    "snowfall": "snowfall",
}
_HOURLY = list(_VAR_MAP.keys())

# Climatological-ish defaults (mild, calm, dry) used when the forecast is
# unavailable. Deliberately benign so a fallback prediction leans on the
# historical/route signal rather than spurious weather.
_DEFAULTS = {
    "temp_2m": 15.0,
    "precip": 0.0,
    "wind_speed": 8.0,
    "wind_gusts": 15.0,
    "snowfall": 0.0,
}

# Open-Meteo forecast horizon is up to 16 days.
_MAX_FORECAST_DAYS = 16


def default_weather() -> dict:
    """The benign fallback weather dict (suffix keys)."""
    return dict(_DEFAULTS)


def fetch_point_weather(
    lat: float,
    lon: float,
    target_date: date,
    dep_hour: int,
    *,
    timeout: float = 4.0,
    client: httpx.Client | None = None,
) -> tuple[dict, bool]:
    """Return (weather_dict, ok). ``ok`` is False when defaults were used.

    Never raises — any failure returns (defaults, False).
    """
    days_out = (target_date - datetime.now(timezone.utc).date()).days
    if days_out < 0 or days_out > _MAX_FORECAST_DAYS:
        log.info(
            "Date %s outside forecast horizon (%+d days); using weather defaults",
            target_date, days_out,
        )
        return default_weather(), False

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(_HOURLY),
        "forecast_days": min(max(days_out + 1, 1), _MAX_FORECAST_DAYS),
        "timezone": "UTC",
    }
    try:
        if client is not None:
            resp = client.get(FORECAST_URL, params=params, timeout=timeout)
        else:
            resp = httpx.get(FORECAST_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — offline/SSL-proxy/timeout all degrade
        log.info("Weather forecast fetch failed (%s); using defaults", exc)
        return default_weather(), False

    return _extract_hour(payload, target_date, dep_hour)
