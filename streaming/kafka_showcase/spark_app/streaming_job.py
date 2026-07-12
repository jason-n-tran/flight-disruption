"""Spark Structured Streaming: ``flight-positions`` -> live airport congestion.

What this demonstrates (the Structured Streaming talking points)
----------------------------------------------------------------
* ``spark.readStream.format("kafka")`` ingestion from Redpanda/Kafka.
* ``from_json`` parse of the message value against an explicit ``StructType``
  schema (mirrors ``producer/messages.py``).
* **Event-time** processing: the event timestamp comes from the OpenSky snapshot
  time carried in the payload (``event_ts``), not Spark's processing clock.
* ``withWatermark`` to bound state and allow late-but-not-too-late data.
* A **tumbling window** aggregation (``window(...)``) counting aircraft per
  ~0.5deg geo-cell -> a live "airport congestion" signal (busy terminal areas
  surface as high-count cells).
* Streaming sinks: console (for the screenshot) + Parquet (durable) and an
  optional re-publish to a Kafka topic ``airport-congestion``.

Run locally (from ``kafka_showcase/``)::

    spark-submit \
      --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 \
      spark_app/streaming_job.py

Config via env (see ``.env.example``): ``KAFKA_BOOTSTRAP_SERVERS``,
``KAFKA_TOPIC``, ``CONGESTION_TOPIC``, ``WINDOW_DURATION``, ``WATERMARK_DELAY``,
``CELL_SIZE_DEG``, ``OUTPUT_PATH``, ``CHECKPOINT_PATH``, ``WRITE_KAFKA``.
"""

from __future__ import annotations

import os
os.environ["HADOOP_HOME"] = r"C:\Users\thism\hadoop"
os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
os.environ["PATH"] = os.environ["HADOOP_HOME"] + r"\bin;" + os.environ.get("PATH", "")
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

# --- Message schema: mirrors producer/messages.MESSAGE_FIELDS exactly ---------
MESSAGE_SCHEMA = StructType(
    [
        StructField("icao24", StringType(), True),
        StructField("callsign", StringType(), True),
        StructField("lat", DoubleType(), True),
        StructField("lon", DoubleType(), True),
        StructField("altitude", DoubleType(), True),
        StructField("velocity", DoubleType(), True),
        StructField("heading", DoubleType(), True),
        StructField("on_ground", BooleanType(), True),
        StructField("event_ts", LongType(), True),  # unix seconds (event-time)
    ]
)


# ---------------------------------------------------------------------------
# Config (env-driven; defaults match docker-compose.kafka.yml + a 16GB machine)
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    return {
        "bootstrap": os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        "topic": os.environ.get("KAFKA_TOPIC", "flight-positions"),
        "congestion_topic": os.environ.get("CONGESTION_TOPIC", "airport-congestion"),
        # Window/watermark are strings Spark parses ("2 minutes", "30 seconds").
        "window_duration": os.environ.get("WINDOW_DURATION", "2 minutes"),
        "slide_duration": os.environ.get("SLIDE_DURATION", "") or None,  # tumbling if blank
        "watermark_delay": os.environ.get("WATERMARK_DELAY", "1 minute"),
        "cell_size": float(os.environ.get("CELL_SIZE_DEG", "0.5")),
        "starting_offsets": os.environ.get("STARTING_OFFSETS", "latest"),
        "output_path": os.environ.get("OUTPUT_PATH", "./data/congestion_parquet"),
        "checkpoint_path": os.environ.get("CHECKPOINT_PATH", "./data/checkpoints/congestion"),
        "write_kafka": os.environ.get("WRITE_KAFKA", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "min_count": int(os.environ.get("MIN_CONGESTION_COUNT", "1")),
    }


def build_spark(app_name: str = "flight-kafka-congestion") -> SparkSession:
    """Create a modest local SparkSession (fits a 16GB machine)."""
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1")
        .getOrCreate()
    )


def read_kafka(spark: SparkSession, cfg: dict) -> DataFrame:
    """Read the raw Kafka stream (key/value/timestamp/offset columns)."""
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", cfg["bootstrap"])
        .option("subscribe", cfg["topic"])
        .option("startingOffsets", cfg["starting_offsets"])
        .option("failOnDataLoss", "false")
        .load()
    )


def parse_positions(raw: DataFrame) -> DataFrame:
    """Parse Kafka value JSON -> typed columns with an event-time timestamp.

    ``event_ts`` (unix seconds) becomes the event-time ``event_time`` timestamp
    that watermarking + windowing operate on.
    """
    parsed = (
        raw.select(
            F.col("key").cast("string").alias("kafka_key"),
            F.from_json(F.col("value").cast("string"), MESSAGE_SCHEMA).alias("p"),
        )
        .select("kafka_key", "p.*")
        .where(F.col("lat").isNotNull() & F.col("lon").isNotNull())
    )
    return parsed.withColumn(
        "event_time", F.to_timestamp(F.from_unixtime(F.col("event_ts")))
    )


def congestion_windows(positions: DataFrame, cfg: dict) -> DataFrame:
    """Windowed count of aircraft per ~CELL_SIZE geo-cell (live congestion).

    Demonstrates: ``withWatermark`` + ``window(...)`` event-time aggregation.
    Tumbling window when ``slide_duration`` is None, else a sliding window.
    """
    cell = cfg["cell_size"]

    # In-bbox filter + cell binning (mirrors spark_app/geo.cell_of).
    binned = (
        positions.where(
            (F.col("lat") >= 24.0)
            & (F.col("lat") <= 50.0)
            & (F.col("lon") >= -125.0)
            & (F.col("lon") <= -66.0)
        )
        .withColumn("cell_lat", F.floor(F.col("lat") / F.lit(cell)) * F.lit(cell))
        .withColumn("cell_lon", F.floor(F.col("lon") / F.lit(cell)) * F.lit(cell))
    )

    win = (
        F.window(F.col("event_time"), cfg["window_duration"], cfg["slide_duration"])
        if cfg["slide_duration"]
        else F.window(F.col("event_time"), cfg["window_duration"])
    )

    agg = (
        binned.withWatermark("event_time", cfg["watermark_delay"])
        .groupBy(win, F.col("cell_lat"), F.col("cell_lon"))
        .agg(
            F.approx_count_distinct("icao24").alias("aircraft_count"),
            F.sum(F.when(F.col("on_ground"), 1).otherwise(0)).alias("on_ground_count"),
            F.round(F.avg("altitude"), 0).alias("avg_altitude_m"),
        )
    )

    return (
        agg.where(F.col("aircraft_count") >= F.lit(cfg["min_count"]))
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            "cell_lat",
            "cell_lon",
            "aircraft_count",
            "on_ground_count",
            "avg_altitude_m",
        )
    )


def run(cfg: dict | None = None) -> None:
    cfg = cfg or _cfg()
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")

    positions = parse_positions(read_kafka(spark, cfg))
    congestion = congestion_windows(positions, cfg)

    queries = []

    # Console sink — the screenshot of the windowed congestion table.
    queries.append(
        congestion.orderBy(F.col("aircraft_count").desc())
        .writeStream.outputMode("complete")
        .format("console")
        .option("truncate", "false")
        .option("numRows", "20")
        .queryName("congestion_console")
        .start()
    )

    # Durable Parquet sink (append mode emits finalized windows past watermark).
    queries.append(
        congestion.writeStream.outputMode("append")
        .format("parquet")
        .option("path", cfg["output_path"])
        .option("checkpointLocation", cfg["checkpoint_path"] + "/parquet")
        .queryName("congestion_parquet")
        .start()
    )

    # Optional: re-publish congestion to Kafka topic ``airport-congestion``.
    if cfg["write_kafka"]:
        kafka_out = congestion.select(
            F.concat_ws(
                ":", F.col("cell_lat").cast("string"), F.col("cell_lon").cast("string")
            ).alias("key"),
            F.to_json(F.struct("*")).alias("value"),
        )
        queries.append(
            kafka_out.writeStream.outputMode("append")
            .format("kafka")
            .option("kafka.bootstrap.servers", cfg["bootstrap"])
            .option("topic", cfg["congestion_topic"])
            .option("checkpointLocation", cfg["checkpoint_path"] + "/kafka")
            .queryName("congestion_kafka")
            .start()
        )

    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    run()
