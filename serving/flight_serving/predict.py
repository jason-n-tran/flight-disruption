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
