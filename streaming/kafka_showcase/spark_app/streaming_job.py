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
