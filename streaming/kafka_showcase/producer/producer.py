"""Producer: OpenSky US-bbox snapshots -> Kafka topic ``flight-positions``.

This is the SHOWCASE ingestion path (the live demo uses NATS elsewhere). It
reuses ``flight_ingest`` for the OpenSky HTTP client, auth, and the state-vector
parser, then fans each aircraft state out as an individual JSON Kafka message
keyed by ``icao24``. Spark Structured Streaming (``spark_app/streaming_job.py``)
consumes the topic and computes live airport-congestion windows.

Design notes
------------
* **Keyed by icao24** so all states for an aircraft share a partition (ordering).
* **Event-time carried in the payload** (``event_ts`` = OpenSky snapshot time) so
  Spark watermarks/windows on event-time, not processing-time.
* **Robust loop**: every network/broker error is logged and the loop continues;
  the producer is meant to be left running for a screenshot session.

Run::

    python -m producer.producer            # from kafka_showcase/, forever
    MAX_POLLS=5 python -m producer.producer # bounded run for a screenshot
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from flight_ingest.config import load_settings as load_ingest_settings
from flight_ingest.opensky import fetch_snapshot

from .config import ProducerSettings, load_settings
from .messages import iter_messages

# Make prints/log unicode-safe on the Windows console (per task spec).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("kafka_showcase.producer")


def _make_kafka_producer(settings: ProducerSettings):
    """Build a ``kafka-python`` ``KafkaProducer``.

    Imported lazily so the module imports (and unit tests on ``messages``) work
    without ``kafka-python`` or a broker installed.
    """
    from kafka import KafkaProducer  # type: ignore

    return KafkaProducer(
        bootstrap_servers=settings.bootstrap_servers.split(","),
        client_id=settings.client_id,
        # Values/keys are already bytes from iter_messages; identity serializers.
        key_serializer=None,
        value_serializer=None,
        acks="all",
        linger_ms=50,         # small batch window — many small position msgs
        retries=3,
        request_timeout_ms=30000,
    )


def publish_snapshot(producer, settings: ProducerSettings, snapshot: dict) -> int:
    """Publish every aircraft in a snapshot as a keyed Kafka message.

    Returns the number of messages sent. The snapshot is the api_contract dict
    from ``flight_ingest.opensky.fetch_snapshot`` (``as_of`` + ``aircraft``).
    """
    event_ts = int(snapshot.get("as_of") or time.time())
    pairs = iter_messages(snapshot.get("aircraft") or [], event_ts)
    for key, value in pairs:
        producer.send(settings.topic, key=key, value=value)
    producer.flush()
    return len(pairs)
