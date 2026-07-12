"""Broker-free tests for the Kafka message (de)serialization contract.

These pin the exact shape the producer publishes and the Spark ``from_json``
schema parses — no Kafka cluster required.
"""

from __future__ import annotations

import json

from producer.messages import (
    MESSAGE_FIELDS,
    build_message,
    deserialize,
    iter_messages,
)

# A realistic parsed-aircraft dict (api_contract shape from parse_state_vector).
SAMPLE_AIRCRAFT = {
    "icao24": "a1b2c3",
    "callsign": "UAL123",
    "lat": 41.97,
    "lon": -87.90,
    "altitude": 10058.4,
    "velocity": 230.1,
    "heading": 270.0,
    "on_ground": False,
}
EVENT_TS = 1781639300


def test_build_message_has_exact_fields():
    msg = build_message(SAMPLE_AIRCRAFT, EVENT_TS)
    assert set(msg.keys()) == set(MESSAGE_FIELDS)
    assert msg["icao24"] == "a1b2c3"
    assert msg["event_ts"] == EVENT_TS
    assert msg["on_ground"] is False


def test_build_message_event_ts_coerced_to_int():
    msg = build_message(SAMPLE_AIRCRAFT, float(EVENT_TS) + 0.9)
    assert msg["event_ts"] == EVENT_TS
    assert isinstance(msg["event_ts"], int)


def test_build_message_missing_optional_fields_become_none():
    sparse = {"icao24": "deadbe", "lat": 30.0, "lon": -90.0}
    msg = build_message(sparse, EVENT_TS)
    assert msg["callsign"] is None
    assert msg["altitude"] is None
    assert msg["on_ground"] is None  # not present -> None (Spark schema nullable)


def test_iter_messages_keys_by_icao24_and_serializes_json():
    pairs = iter_messages([SAMPLE_AIRCRAFT], EVENT_TS)
    assert len(pairs) == 1
    key, value = pairs[0]
    assert key == b"a1b2c3"
    decoded = json.loads(value)
    assert decoded["callsign"] == "UAL123"
    assert decoded["event_ts"] == EVENT_TS


def test_iter_messages_skips_aircraft_without_icao24():
    aircraft = [
        SAMPLE_AIRCRAFT,
        {"icao24": None, "lat": 1.0, "lon": 2.0},   # dropped: no key
        {"icao24": "", "lat": 1.0, "lon": 2.0},      # dropped: empty key
        {"icao24": "ffeedd", "lat": 35.0, "lon": -97.0},
    ]
    pairs = iter_messages(aircraft, EVENT_TS)
    keys = [k for k, _ in pairs]
    assert keys == [b"a1b2c3", b"ffeedd"]


def test_roundtrip_deserialize_matches_build():
    _, value = iter_messages([SAMPLE_AIRCRAFT], EVENT_TS)[0]
    assert deserialize(value) == build_message(SAMPLE_AIRCRAFT, EVENT_TS)
    # bytes and str inputs both work
    assert deserialize(value.decode("utf-8")) == deserialize(value)


def test_value_is_compact_json():
    _, value = iter_messages([SAMPLE_AIRCRAFT], EVENT_TS)[0]
    # compact separators -> no spaces after ':' or ','
    assert b", " not in value and b": " not in value
