"""Stage 2 — gold: per-flight ML feature table ``fct_flight_features``.

THE leakage-sensitive component. Output columns are EXACTLY
``MODEL_FEATURES + [LABEL_COLUMN] + identity cols`` and the build asserts that
none of ``BANNED_LEAKY_COLUMNS`` (snake_cased) leaked in.

----------------------------------------------------------------------------
Leakage-safe rolling reliability (the portfolio talking point)
----------------------------------------------------------------------------
``route_hist_delay_rate`` / ``origin_hist_delay_rate`` / ``carrier_hist_delay_rate``
are the mean of the label (dep_del15) over flights that departed STRICTLY
BEFORE the current flight's date. We never let the current day (or any future
day) contribute to its own feature.

Implementation: aggregate the label to a per-entity-per-day (count, sum), then
take a cumulative count/sum over a window ordered by an integer day number with
``rangeBetween(Window.unboundedPreceding, -1)`` — the ``-1`` upper bound is what
makes it EXCLUSIVE of the current day. The rate = prior_sum / prior_count.
Rows with no prior history (cold start) get the global historical rate as a
neutral fill. We then join those per-day priors back onto each flight by
(entity, day). Because the prior for day D depends only on days < D, two flights
on the same day share the same (history-only) feature value and neither sees the
other — no same-day leakage either.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql.window import Window

from flight_contracts.contract import (
    BANNED_LEAKY_COLUMNS,
    GOLD_FEATURES_TABLE,
    LABEL_COLUMN,
    MODEL_FEATURES,
)

from .config import SILVER_FLIGHTS, SILVER_WEATHER, LakeConfig
from .session import write_table

# Identity columns carried alongside features + label (for the temporal split
# and joins downstream). NOT model features.
IDENTITY_COLUMNS = ["flight_date", "carrier", "origin", "dest", "year"]

# Sensible weather fills when the hourly join misses (sparse archive coverage).
# precip/snow default to 0 (no precipitation); temp/wind to mild constants.
WEATHER_FILL = {
    "temp_2m": 15.0,      # deg C, mild
    "precip": 0.0,        # mm
    "wind_speed": 10.0,   # km/h
    "wind_gusts": 15.0,   # km/h
    "snowfall": 0.0,      # cm
}

# weather var (silver) -> feature suffix
WEATHER_VAR_TO_SUFFIX = {
    "temperature_2m": "temp_2m",
    "precipitation": "precip",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_gusts",
    "snowfall": "snowfall",
}


def _day_number(date_col):
    """Integer day number (days since epoch) for range-window ordering."""
    return F.datediff(date_col, F.lit("1970-01-01")).cast(T.LongType())


def _hist_rate(
    flights: DataFrame,
    key_cols: list[str],
    out_col: str,
    global_prior: float,
) -> DataFrame:
    """Leakage-safe historical delay rate for ``key_cols``, joined per (key, day).

    Returns a DataFrame of [*key_cols, day_num, out_col] giving, for each
    (entity, day) that appears in the data, the mean label over all PRIOR days.
    """
    daily = (
        flights.groupBy(*key_cols, "day_num")
        .agg(
            F.sum(F.col(LABEL_COLUMN)).alias("_day_sum"),
            F.count(F.lit(1)).alias("_day_cnt"),
        )
    )

    # Cumulative over prior days only: rangeBetween(..., -1) EXCLUDES current day.
    w = (
        Window.partitionBy(*key_cols)
        .orderBy("day_num")
        .rangeBetween(Window.unboundedPreceding, -1)
    )
    prior_sum = F.sum("_day_sum").over(w)
    prior_cnt = F.sum("_day_cnt").over(w)

    out = daily.select(
        *key_cols,
        "day_num",
        F.when(
            prior_cnt > 0, prior_sum.cast(T.DoubleType()) / prior_cnt
        ).otherwise(F.lit(global_prior)).alias(out_col),
    )
    return out
