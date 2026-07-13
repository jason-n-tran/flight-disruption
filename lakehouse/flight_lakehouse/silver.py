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
