"""Serve-time feature assembly + scoring for ``/api/predict``.

This is the bridge between the thin API request (origin, dest, carrier, date,
dep_hour) and the full ``MODEL_FEATURES`` vector the model expects. The single
reference scoring function lives in ``flight_ml.artifacts.predict_proba_one`` —
we DO NOT reinvent inference; we only build the feature dict it consumes.

How each feature is derived at serve time
-----------------------------------------
* categorical: origin, dest, carrier come from the request; ``dep_hour``,
  ``day_of_week``, ``month``, ``time_of_day_bucket`` are derived from date+hour.
* ``distance`` / ``crs_elapsed_time``: median for the route from the gold feature
  table; if the route is unseen, distance is the great-circle from airport coords
  and elapsed time is estimated from distance.
* ``is_holiday_window``: +/-2 days of a US federal holiday (inlined list).
* rolling reliability (``route_/origin_/carrier_hist_delay_rate``): the gold
  aggregate delay rates serve as the serve-time historical values. These mirror
  the leakage-safe rolling features the model trained on. If an aggregate is
  missing, we fall back to the baseline route rate / global prior from the
  artifact's ``feature_metadata.json``.
* weather (10 vars): live Open-Meteo forecast for origin + dest at dep_hour, with
  graceful fallback to climatological defaults (so /api/predict never fails).
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime

from flight_ml.artifacts import Artifacts, predict_proba_one

from .holidays import is_holiday_window
from .queries import GoldStore
from .weather import default_weather, fetch_point_weather

log = logging.getLogger("flight_serving.predict")


def _time_of_day_bucket(dep_hour: int) -> str:
    if dep_hour < 6:
        return "night"
    if dep_hour < 12:
        return "morning"
    if dep_hour < 18:
        return "afternoon"
    return "evening"


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8  # earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_feature_dict(
    *,
    store: GoldStore,
    artifacts: Artifacts,
    origin: str,
    dest: str,
    carrier: str,
    date_str: str,
    dep_hour: int,
    weather_client=None,
    weather_enabled: bool = True,
    weather_timeout: float = 4.0,
) -> tuple[dict, dict, bool]:
    """Assemble the full MODEL_FEATURES dict.

    Returns ``(feature_dict, weather_summary, weather_ok)``.
    """
    d = _parse_date(date_str)

    # --- derived calendar features ---
    day_of_week = d.isoweekday()  # 1=Mon .. 7=Sun (matches BTS DayOfWeek)
    month = d.month
    tod = _time_of_day_bucket(dep_hour)

    # --- distance / elapsed time ---
    distance, crs_elapsed = store.route_distance(origin, dest)
    if distance is None:
        a = store.airport_dim(origin)
        b = store.airport_dim(dest)
        if a and b:
            distance = round(_haversine_miles(a["lat"], a["lon"], b["lat"], b["lon"]), 0)
        else:
            distance = 800.0  # league-average fallback
    if crs_elapsed is None:
        # rough block time: cruise ~7 mi/min + ~40 min taxi/climb/descent
        crs_elapsed = round(distance / 7.0 + 40.0, 0)

    # --- holiday window ---
    holiday = 1.0 if is_holiday_window(d) else 0.0

    # --- rolling reliability (gold aggregates, with baseline fallback) ---
    rates = store.hist_rates(origin, dest, carrier)
    route_rate = rates["route_hist_delay_rate"]
    origin_rate = rates["origin_hist_delay_rate"]
    carrier_rate = rates["carrier_hist_delay_rate"]
    base_route = float(artifacts.baseline.predict_one(origin, dest))
    prior = float(artifacts.baseline.global_prior)
    if route_rate is None:
        route_rate = base_route
    if origin_rate is None:
        origin_rate = prior
    if carrier_rate is None:
        carrier_rate = prior

    # --- weather forecast (origin + dest) with graceful fallback ---
    weather_ok = False
    if weather_enabled:
        o = store.airport_dim(origin)
        dst = store.airport_dim(dest)
        if o:
            ow, ook = fetch_point_weather(
                o["lat"], o["lon"], d, dep_hour,
                timeout=weather_timeout, client=weather_client,
            )
        else:
            ow, ook = default_weather(), False
        if dst:
            dw, dok = fetch_point_weather(
                dst["lat"], dst["lon"], d, dep_hour,
                timeout=weather_timeout, client=weather_client,
            )
        else:
            dw, dok = default_weather(), False
        weather_ok = ook or dok
    else:
        ow, dw = default_weather(), default_weather()

    feature_dict = {
        # categorical
        "origin": origin,
        "dest": dest,
        "carrier": carrier,
        "dep_hour": int(dep_hour),
        "day_of_week": int(day_of_week),
        "month": int(month),
        "time_of_day_bucket": tod,
        # numeric
        "distance": float(distance),
        "crs_elapsed_time": float(crs_elapsed),
        "is_holiday_window": holiday,
        "route_hist_delay_rate": float(route_rate),
        "origin_hist_delay_rate": float(origin_rate),
        "carrier_hist_delay_rate": float(carrier_rate),
        "origin_temp_2m": ow["temp_2m"],
        "origin_precip": ow["precip"],
        "origin_wind_speed": ow["wind_speed"],
        "origin_wind_gusts": ow["wind_gusts"],
        "origin_snowfall": ow["snowfall"],
        "dest_temp_2m": dw["temp_2m"],
        "dest_precip": dw["precip"],
        "dest_wind_speed": dw["wind_speed"],
        "dest_wind_gusts": dw["wind_gusts"],
        "dest_snowfall": dw["snowfall"],
    }

    weather_summary = {
        "origin": {
            "temp_c": round(ow["temp_2m"], 1),
            "precip_mm": round(ow["precip"], 2),
            "wind_gusts": round(ow["wind_gusts"], 1),
        },
        "dest": {
            "temp_c": round(dw["temp_2m"], 1),
            "precip_mm": round(dw["precip"], 2),
            "wind_gusts": round(dw["wind_gusts"], 1),
        },
        "forecast_available": weather_ok,
    }
    return feature_dict, weather_summary, weather_ok
