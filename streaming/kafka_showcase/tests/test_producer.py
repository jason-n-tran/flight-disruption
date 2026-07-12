"""Broker-free test of producer.publish_snapshot using a fake KafkaProducer.

Verifies the producer fans a snapshot out into one keyed message per aircraft on
the configured topic, carrying the snapshot ``as_of`` as event-time — without a
running Kafka cluster.
"""

from __future__ import annotations

import json

from producer.config import ProducerSettings
from producer.messages import deserialize
from producer.producer import publish_snapshot


class FakeKafkaProducer:
    """Minimal stand-in: records send() calls and flushes."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.flushed = 0

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key, value))

    def flush(self):
        self.flushed += 1


def _settings() -> ProducerSettings:
    return ProducerSettings(
        bootstrap_servers="localhost:19092",
        topic="flight-positions",
        poll_interval_seconds=60.0,
        max_polls=0,
        client_id="test",
    )


def _snapshot(n=3, as_of=1781639300):
    return {
        "as_of": as_of,
        "stale_seconds": 0,
        "source": "live",
        "count": n,
        "aircraft": [
            {
                "icao24": f"ac{i:04d}",
                "callsign": f"TST{i}",
                "lat": 40.0 + i,
                "lon": -90.0 - i,
                "altitude": 10000.0,
                "velocity": 200.0,
                "heading": 90.0,
                "on_ground": False,
            }
            for i in range(n)
        ],
    }


def test_publish_snapshot_sends_one_message_per_aircraft():
    producer = FakeKafkaProducer()
    settings = _settings()
    sent = publish_snapshot(producer, settings, _snapshot(3))

    assert sent == 3
    assert len(producer.sent) == 3
    assert producer.flushed == 1
    assert all(topic == "flight-positions" for topic, _, _ in producer.sent)


def test_publish_snapshot_carries_event_ts_from_as_of():
    producer = FakeKafkaProducer()
    publish_snapshot(producer, _settings(), _snapshot(2, as_of=1781639300))

    for _topic, key, value in producer.sent:
        msg = deserialize(value)
        assert msg["event_ts"] == 1781639300
        assert key.decode("utf-8") == msg["icao24"]


def test_publish_snapshot_empty_aircraft_sends_nothing():
    producer = FakeKafkaProducer()
    sent = publish_snapshot(producer, _settings(), {"as_of": 1, "aircraft": []})
    assert sent == 0
    assert producer.sent == []
    # still flushes (harmless no-op)
    assert producer.flushed == 1


def test_publish_snapshot_skips_keyless_aircraft():
    producer = FakeKafkaProducer()
    snap = _snapshot(1)
    snap["aircraft"].append({"icao24": None, "lat": 1.0, "lon": 2.0})
    sent = publish_snapshot(producer, _settings(), snap)
    assert sent == 1  # the keyless one is dropped
