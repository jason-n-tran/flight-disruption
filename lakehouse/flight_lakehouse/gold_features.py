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


def build_gold_features(spark: SparkSession, cfg: LakeConfig) -> DataFrame:
    """Build ``gold/fct_flight_features`` (parquet partitioned by year)."""
    flights = spark.read.format(
        "delta" if cfg.is_delta else "parquet"
    ).load(cfg.paths.silver_table(SILVER_FLIGHTS))
    weather = spark.read.format(
        "delta" if cfg.is_delta else "parquet"
    ).load(cfg.paths.silver_table(SILVER_WEATHER))

    flights = flights.withColumn("day_num", _day_number(F.col("flight_date")))

    # Global historical prior — overall mean label across the whole dataset.
    # Used as the cold-start fill for entities/days with no prior history.
    global_prior = flights.select(
        F.avg(F.col(LABEL_COLUMN).cast(T.DoubleType()))
    ).first()[0]
    if global_prior is None:
        global_prior = 0.0

    # --- Rolling reliability features (leakage-safe) ---------------------------
    route_hist = _hist_rate(
        flights, ["origin", "dest"], "route_hist_delay_rate", global_prior
    )
    origin_hist = _hist_rate(
        flights, ["origin"], "origin_hist_delay_rate", global_prior
    )
    carrier_hist = _hist_rate(
        flights, ["carrier"], "carrier_hist_delay_rate", global_prior
    )

    feats = (
        flights.join(route_hist, ["origin", "dest", "day_num"], "left")
        .join(origin_hist, ["origin", "day_num"], "left")
        .join(carrier_hist, ["carrier", "day_num"], "left")
    )
    # Any join miss (shouldn't happen since keys come from the same data) ->
    # global prior, keeping the column non-null.
    for c in (
        "route_hist_delay_rate",
        "origin_hist_delay_rate",
        "carrier_hist_delay_rate",
    ):
        feats = feats.withColumn(
            c, F.coalesce(F.col(c), F.lit(global_prior))
        )

    # --- Weather features at ORIGIN and DEST ----------------------------------
    # Match each flight to the weather row at the airport for the flight's
    # scheduled hour. For DEST we use the SAME scheduled hour as the origin
    # departure — a documented simplification (we don't model en-route time for
    # the destination-weather proxy; arrival-hour weather would also be a
    # weaker pre-departure signal).
    feats = feats.withColumn(
        "weather_hour_key",
        (
            F.year("flight_ts") * F.lit(1000000)
            + F.month("flight_ts") * F.lit(10000)
            + F.dayofmonth("flight_ts") * F.lit(100)
            + F.hour("flight_ts")
        ).cast(T.LongType()),
    )

    feats = _join_weather(feats, weather, side="origin")
    feats = _join_weather(feats, weather, side="dest")

    # --- Assemble the exact contract column set --------------------------------
    select_exprs = []
    for col in MODEL_FEATURES:
        select_exprs.append(F.col(col).alias(col))
    select_exprs.append(F.col(LABEL_COLUMN).alias(LABEL_COLUMN))
    for col in IDENTITY_COLUMNS:
        if col not in MODEL_FEATURES and col != LABEL_COLUMN:
            select_exprs.append(F.col(col).alias(col))

    out = feats.select(*select_exprs)

    _assert_contract(out)

    write_table(
        out, cfg.paths.gold_table(GOLD_FEATURES_TABLE), cfg, partition_by=["year"]
    )
    return out


def _join_weather(feats: DataFrame, weather: DataFrame, side: str) -> DataFrame:
    """Join weather for ``side`` ('origin'|'dest') at the scheduled hour.

    Produces ``{side}_temp_2m``, ``{side}_precip``, ``{side}_wind_speed``,
    ``{side}_wind_gusts``, ``{side}_snowfall`` with null -> sensible defaults.
    """
    join_iata = "origin" if side == "origin" else "dest"

    w = weather.select(
        F.col("iata").alias("_w_iata"),
        F.col("weather_hour_key").alias("_w_key"),
        *[
            F.col(var).alias(f"_w_{suffix}")
            for var, suffix in WEATHER_VAR_TO_SUFFIX.items()
        ],
    )

    joined = feats.join(
        w,
        (feats[join_iata] == w["_w_iata"])
        & (feats["weather_hour_key"] == w["_w_key"]),
        "left",
    )

    for var, suffix in WEATHER_VAR_TO_SUFFIX.items():
        out_col = f"{side}_{suffix}"
        joined = joined.withColumn(
            out_col,
            F.coalesce(
                F.col(f"_w_{suffix}").cast(T.DoubleType()),
                F.lit(WEATHER_FILL[suffix]),
            ),
        )

    drop_cols = ["_w_iata", "_w_key"] + [
        f"_w_{suffix}" for suffix in WEATHER_VAR_TO_SUFFIX.values()
    ]
    return joined.drop(*drop_cols)
