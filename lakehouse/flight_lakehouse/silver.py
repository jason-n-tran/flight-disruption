"""Stage 1 — silver: clean + conform bronze BTS / airports / weather.

Outputs:
    silver/flights  : one row per scheduled flight, conformed + derived columns.
                      Keeps the label AND the dashboard-only columns (delay
                      minutes, cancelled, diverted, cause columns) so the dbt
                      agg marts can use them. Those columns are dropped at the
                      gold feature stage (see gold_features.py) so they never
                      reach the model.
    silver/airports : pass-through + dedupe of the airports dim.
    silver/weather  : weather with ``time`` parsed to a timestamp.

Read-side note: bronze BTS is parquet partitioned year=/month=; weather is
parquet partitioned iata=; airports is a flat parquet dir. Spark's parquet
reader discovers the partitions automatically.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

from flight_contracts.contract import LABEL_COLUMN, WEATHER_ARCHIVE_VARS

from .config import (
    BRONZE_AIRPORTS,
    BRONZE_BTS,
    BRONZE_WEATHER,
    SILVER_AIRPORTS,
    SILVER_FLIGHTS,
    SILVER_WEATHER,
    LakeConfig,
)
from .holidays import holiday_window_dates
from .session import write_table

# ---------------------------------------------------------------------------
# Dashboard-only columns: kept in silver for dbt agg marts, NEVER in gold model
# features. (All are after-the-fact / banned-as-features.)
# ---------------------------------------------------------------------------
DASHBOARD_ONLY_COLUMNS = [
    "dep_delay_minutes",
    "arr_del15",
    "cancelled",
    "diverted",
    "carrier_delay",
    "weather_delay",
    "nas_delay",
    "security_delay",
    "late_aircraft_delay",
]


def _time_of_day_bucket(dep_hour_col):
    """night [0-6) / morning [6-12) / afternoon [12-18) / evening [18-24)."""
    return (
        F.when(dep_hour_col < 6, F.lit("night"))
        .when(dep_hour_col < 12, F.lit("morning"))
        .when(dep_hour_col < 18, F.lit("afternoon"))
        .otherwise(F.lit("evening"))
    )


def build_silver_airports(spark: SparkSession, cfg: LakeConfig) -> DataFrame:
    """Conform airports: pass-through + dedupe on iata (keep first)."""
    src = spark.read.parquet(cfg.paths.bronze_table(BRONZE_AIRPORTS))
    out = (
        src.select(
            F.col("iata").cast(T.StringType()).alias("iata"),
            F.col("name").cast(T.StringType()).alias("name"),
            F.col("city").cast(T.StringType()).alias("city"),
            F.col("lat").cast(T.DoubleType()).alias("lat"),
            F.col("lon").cast(T.DoubleType()).alias("lon"),
            F.col("tz").cast(T.StringType()).alias("tz"),
        )
        .where(F.col("iata").isNotNull())
        .dropDuplicates(["iata"])
    )
    write_table(out, cfg.paths.silver_table(SILVER_AIRPORTS), cfg)
    return out


def build_silver_weather(spark: SparkSession, cfg: LakeConfig) -> DataFrame:
    """Conform weather: parse ISO-hour ``time`` to timestamp, keep archive vars.

    Adds ``weather_ts`` (timestamp) and an integer ``weather_hour_key`` =
    yyyymmddHH used as a cheap exact-hour join key downstream.
    """
    src = spark.read.parquet(cfg.paths.bronze_table(BRONZE_WEATHER))
    # `time` is written as a real (microsecond) timestamp by the ingester. Cast
    # to timestamp directly; fall back to string parsing only if it's text. (The
    # explicit string format would null-out an already-timestamp column.)
    time_type = dict(src.dtypes).get("time", "")
    if time_type.startswith("timestamp"):
        ts = F.col("time").cast(T.TimestampType())
    else:
        ts = F.to_timestamp(F.col("time"), "yyyy-MM-dd'T'HH:mm")
    out = src.select(
        F.col("iata").cast(T.StringType()).alias("iata"),
        ts.alias("weather_ts"),
        *[F.col(v).cast(T.DoubleType()).alias(v) for v in WEATHER_ARCHIVE_VARS],
    ).where(F.col("iata").isNotNull() & ts.isNotNull())

    out = out.withColumn(
        "weather_hour_key",
        (
            F.year("weather_ts") * F.lit(1000000)
            + F.month("weather_ts") * F.lit(10000)
            + F.dayofmonth("weather_ts") * F.lit(100)
            + F.hour("weather_ts")
        ).cast(T.LongType()),
    ).dropDuplicates(["iata", "weather_hour_key"])

    write_table(out, cfg.paths.silver_table(SILVER_WEATHER), cfg)
    return out


def build_silver_flights(
    spark: SparkSession, cfg: LakeConfig, airports: DataFrame
) -> DataFrame:
    """Clean + conform BTS on-time into silver/flights.

    Steps: filter to scheduled flights with valid origin/dest in the airports
    dim and a non-null label; derive dep_hour / time_of_day_bucket / flight_ts /
    is_holiday_window; rename reporting_airline -> carrier; cast types.
    """
    bts = spark.read.parquet(cfg.paths.bronze_table(BRONZE_BTS))

    valid_iata = airports.select("iata").distinct()

    df = (
        bts
        # scheduled flights only: must have a CRS dep time and a label.
        .where(F.col("crs_dep_time").isNotNull())
        .where(F.col(LABEL_COLUMN).isNotNull())
        .where(F.col("origin").isNotNull() & F.col("dest").isNotNull())
    )

    # dep_hour: crs_dep_time is int HHMM (e.g. 1705 -> 17). BTS encodes midnight
    # as 2400 sometimes; clamp to 0-23. (Spark Columns have no // operator -> use
    # floor of integer division.)
    raw_hour = F.floor(F.col("crs_dep_time").cast(T.IntegerType()) / F.lit(100))
    dep_hour = (
        F.when(raw_hour > 23, F.lit(0))
        .when(raw_hour < 0, F.lit(0))
        .otherwise(raw_hour)
        .cast(T.IntegerType())
    )

    df = (
        df.withColumn("carrier", F.col("reporting_airline").cast(T.StringType()))
        .withColumn("origin", F.col("origin").cast(T.StringType()))
        .withColumn("dest", F.col("dest").cast(T.StringType()))
        .withColumn("year", F.col("year").cast(T.IntegerType()))
        .withColumn("month", F.col("month").cast(T.IntegerType()))
        .withColumn("day_of_week", F.col("day_of_week").cast(T.IntegerType()))
        .withColumn("flight_date", F.to_date(F.col("flight_date")))
        .withColumn("dep_hour", dep_hour)
        .withColumn("time_of_day_bucket", _time_of_day_bucket(F.col("dep_hour")))
        .withColumn("distance", F.col("distance").cast(T.DoubleType()))
        .withColumn(
            "crs_elapsed_time", F.col("crs_elapsed_time").cast(T.DoubleType())
        )
        .withColumn(
            "flight_number_reporting_airline",
            F.col("flight_number_reporting_airline").cast(T.StringType()),
        )
        .withColumn("crs_dep_time", F.col("crs_dep_time").cast(T.IntegerType()))
        .withColumn("crs_arr_time", F.col("crs_arr_time").cast(T.IntegerType()))
        .withColumn(LABEL_COLUMN, F.col(LABEL_COLUMN).cast(T.IntegerType()))
    )

    # flight_ts: a real timestamp from flight_date + dep_hour (top of the
    # scheduled departure hour). Used to order flights and to join weather.
    df = df.withColumn(
        "flight_ts",
        F.to_timestamp(
            F.concat_ws(
                " ",
                F.date_format("flight_date", "yyyy-MM-dd"),
                F.format_string("%02d:00:00", F.col("dep_hour")),
            ),
            "yyyy-MM-dd HH:mm:ss",
        ),
    )

    # is_holiday_window: flag flights within +/- 2 days of a US federal holiday.
    # The +/-2-day envelope is a small literal set (~600 dates), so we use a pure
    # SQL ``isin`` predicate (a JVM-side In-list) rather than a join — this keeps
    # the whole silver build on JVM operators with no Python-worker round trip.
    window_dates = sorted(holiday_window_dates(window_days=2))
    flight_date_str = F.date_format("flight_date", "yyyy-MM-dd")
    df = df.withColumn(
        "is_holiday_window",
        F.when(flight_date_str.isin(window_dates), F.lit(1)).otherwise(F.lit(0)),
    )

    # Keep flights whose origin AND dest are in the airports dim.
    df = (
        df.join(
            F.broadcast(valid_iata.withColumnRenamed("iata", "_o")),
            F.col("origin") == F.col("_o"),
            "left_semi",
        )
        .join(
            F.broadcast(valid_iata.withColumnRenamed("iata", "_d")),
            F.col("dest") == F.col("_d"),
            "left_semi",
        )
    )

    # Dashboard-only columns: cast through, default missing to null. These are
    # carried in silver for dbt aggregates, dropped before gold features.
    for c in DASHBOARD_ONLY_COLUMNS:
        if c in df.columns:
            df = df.withColumn(c, F.col(c).cast(T.DoubleType()))
        else:
            df = df.withColumn(c, F.lit(None).cast(T.DoubleType()))

    select_cols = [
        # identity / time
        "flight_date",
        "flight_ts",
        "year",
        "month",
        "day_of_week",
        "carrier",
        "flight_number_reporting_airline",
        "origin",
        "dest",
        # scheduled / pre-departure-safe features
        "dep_hour",
        "time_of_day_bucket",
        "distance",
        "crs_dep_time",
        "crs_arr_time",
        "crs_elapsed_time",
        "is_holiday_window",
        # label
        LABEL_COLUMN,
    ] + DASHBOARD_ONLY_COLUMNS

    out = df.select(*select_cols)
    write_table(out, cfg.paths.silver_table(SILVER_FLIGHTS), cfg, partition_by=["year"])
    return out


def build_silver(spark: SparkSession, cfg: LakeConfig) -> dict[str, DataFrame]:
    """Build all three silver tables. Airports first (flights filters on it)."""
    airports = build_silver_airports(spark, cfg)
    weather = build_silver_weather(spark, cfg)
    flights = build_silver_flights(spark, cfg, airports)
    return {"airports": airports, "weather": weather, "flights": flights}
