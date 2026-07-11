"""Tests for the raw->contract transform and the viewer-gated interval logic."""

from __future__ import annotations

from flight_stream.transform import (
    AIRCRAFT_FIELDS,
    choose_interval,
    snapshot_to_payload,
    viewer_is_active,
)

# A raw OpenSky states/all payload. Indices: 0 icao24,1 callsign,5 lon,6 lat,
# 7 baro_alt,8 on_ground,9 velocity,10 true_track,13 geo_alt.
RAW_OPENSKY = {
    "time": 1781639300,
    "states": [
        # full vector
        ["ab1644", "UAL1091 ", "United States", 1781639290, 1781639295,
         -96.42, 29.33, 6000.0, False, 209.6, 43.6, -1.0, None, 6606.5,
         None, False, 0],
        # on-ground, no callsign
        ["c0ffee", None, "United States", 1781639290, 1781639295,
         -80.0, 26.0, None, True, 0.0, 0.0, 0.0, None, 12.0, None, False, 0],
        # no position -> dropped
        ["deadbe", "NONE", "United States", 1781639290, 1781639295,
         None, None, None, False, None, None, None, None, None, None, False, 0],
    ],
}


def test_transform_from_raw_states_produces_contract_shape():
    payload = snapshot_to_payload(RAW_OPENSKY, now=1781639312)

    # Top-level contract fields.
    assert set(payload) == {"as_of", "stale_seconds", "source", "count", "aircraft"}
    assert payload["source"] == "live"
    assert payload["as_of"] == 1781639300
    assert payload["stale_seconds"] == 12  # 1781639312 - 1781639300
    # The position-less entry is dropped.
    assert payload["count"] == 2
    assert len(payload["aircraft"]) == 2


def test_transform_aircraft_fields_exact_and_clean():
    payload = snapshot_to_payload(RAW_OPENSKY, now=1781639312)
    a = payload["aircraft"][0]

    # Exactly the contract fields, nothing more.
    assert set(a) == set(AIRCRAFT_FIELDS)
    assert a["icao24"] == "ab1644"
    assert a["callsign"] == "UAL1091"   # trimmed
    assert a["lat"] == 29.33
    assert a["lon"] == -96.42
    assert a["altitude"] == 6606.5      # geo altitude preferred over baro
    assert a["velocity"] == 209.6
    assert a["heading"] == 43.6
    assert a["on_ground"] is False

    # on-ground entry: empty callsign normalized to None, baro fallback altitude.
    b = payload["aircraft"][1]
    assert b["callsign"] is None
    assert b["on_ground"] is True
    assert b["altitude"] == 12.0


def test_transform_accepts_already_parsed_snapshot():
    parsed = {
        "as_of": 1700000000,
        "aircraft": [
            {"icao24": "x", "callsign": "Y", "lat": 1.0, "lon": 2.0,
             "altitude": 3.0, "velocity": 4.0, "heading": 5.0, "on_ground": False,
             "extra": "should be dropped"},
        ],
    }
    payload = snapshot_to_payload(parsed, now=1700000005)
    assert payload["count"] == 1
    assert payload["as_of"] == 1700000000
    assert payload["stale_seconds"] == 5
    assert set(payload["aircraft"][0]) == set(AIRCRAFT_FIELDS)  # extra dropped


def test_count_matches_aircraft_length():
    payload = snapshot_to_payload(RAW_OPENSKY, now=1781639312)
    assert payload["count"] == len(payload["aircraft"])


# ---- viewer-gated interval ----

def test_viewer_active_recent_true():
    now = 1000.0
    assert viewer_is_active("940", window_seconds=300, now=now) is True


def test_viewer_active_stale_false():
    now = 1000.0
    assert viewer_is_active("600", window_seconds=300, now=now) is False


def test_viewer_active_none_false():
    assert viewer_is_active(None, window_seconds=300, now=1000.0) is False


def test_viewer_active_garbage_false():
    assert viewer_is_active("not-a-number", window_seconds=300, now=1000.0) is False


def test_choose_interval_recent_viewer_uses_poll():
    now = 1000.0
    interval = choose_interval(
        "950",
        poll_interval_seconds=60,
        idle_interval_seconds=600,
        viewer_active_window_seconds=300,
        now=now,
    )
    assert interval == 60


def test_choose_interval_no_viewer_uses_idle():
    now = 1000.0
    interval = choose_interval(
        None,
        poll_interval_seconds=60,
        idle_interval_seconds=600,
        viewer_active_window_seconds=300,
        now=now,
    )
    assert interval == 600


def test_choose_interval_stale_viewer_uses_idle():
    now = 1000.0
    interval = choose_interval(
        "500",  # 500s ago > 300s window
        poll_interval_seconds=60,
        idle_interval_seconds=600,
        viewer_active_window_seconds=300,
        now=now,
    )
    assert interval == 600
