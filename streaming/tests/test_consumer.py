"""Tests for the consumer: NATS message -> Valkey keys with the contract shape."""

from __future__ import annotations

import json

import fakeredis
import pytest

from flight_contracts import valkey_key
from flight_stream.config import load_settings
from flight_stream.consumer import _handle_message
from flight_stream.transform import AIRCRAFT_FIELDS
from flight_stream.valkey_io import write_positions


class _FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.acked = False

    async def ack(self) -> None:
        self.acked = True


RAW_SNAPSHOT = {
    "as_of": 1781639300,
    "aircraft": [
        {"icao24": "ab1644", "callsign": "UAL1091", "lat": 29.33, "lon": -96.42,
         "altitude": 6606.5, "velocity": 209.6, "heading": 43.6, "on_ground": False},
        {"icao24": "c0ffee", "callsign": None, "lat": 26.0, "lon": -80.0,
         "altitude": 12.0, "velocity": 0.0, "heading": 0.0, "on_ground": True},
    ],
}


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def fake_valkey():
    return fakeredis.FakeRedis(decode_responses=True)


async def test_handle_message_writes_both_keys(settings, fake_valkey):
    msg = _FakeMsg(json.dumps(RAW_SNAPSHOT).encode("utf-8"))

    # Inject the fake client by monkeypatching make_valkey via direct call.
    await _handle_message_with_client(msg, settings, fake_valkey)

    latest = fake_valkey.get(valkey_key("positions", "latest"))
    cached = fake_valkey.get(valkey_key("positions", "cached"))
    assert latest is not None
    assert cached is not None

    latest_payload = json.loads(latest)
    cached_payload = json.loads(cached)

    # Contract shape on the live key.
    assert set(latest_payload) == {"as_of", "stale_seconds", "source", "count", "aircraft"}
    assert latest_payload["source"] == "live"
    assert latest_payload["count"] == 2
    assert set(latest_payload["aircraft"][0]) == set(AIRCRAFT_FIELDS)

    # Cached fallback is relabeled.
    assert cached_payload["source"] == "cached"
    assert cached_payload["count"] == 2

    assert msg.acked is True


async def test_handle_message_ttls_set(settings, fake_valkey):
    msg = _FakeMsg(json.dumps(RAW_SNAPSHOT).encode("utf-8"))
    await _handle_message_with_client(msg, settings, fake_valkey)

    ttl_latest = fake_valkey.ttl(valkey_key("positions", "latest"))
    ttl_cached = fake_valkey.ttl(valkey_key("positions", "cached"))
    assert 0 < ttl_latest <= settings.positions_ttl_seconds
    assert ttl_latest <= ttl_cached  # cached lives longer
    assert ttl_cached <= settings.positions_cached_ttl_seconds


async def test_handle_message_poison_is_acked_not_raised(settings, fake_valkey):
    msg = _FakeMsg(b"{not valid json")
    # Should not raise; should ack and skip.
    await _handle_message_with_client(msg, settings, fake_valkey)
    assert msg.acked is True
    assert fake_valkey.get(valkey_key("positions", "latest")) is None


def test_write_positions_directly(settings, fake_valkey):
    payload = {
        "as_of": 1, "stale_seconds": 0, "source": "live", "count": 1,
        "aircraft": [dict.fromkeys(AIRCRAFT_FIELDS, None)],
    }
    write_positions(fake_valkey, payload, settings)
    assert fake_valkey.exists(valkey_key("positions", "latest"))
    assert fake_valkey.exists(valkey_key("positions", "cached"))


# --- helper: run _handle_message but with an injected valkey client ---
async def _handle_message_with_client(msg, settings, client):
    """_handle_message takes the client as an arg, so just call it directly."""
    await _handle_message(msg, settings, client)
