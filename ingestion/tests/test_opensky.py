"""OpenSky parsing tests: state-vector mapping, anon fallback, snapshot shape."""

from __future__ import annotations

from flight_ingest import opensky


def _sample_state():
    # Real-shaped state vector. Indices: 0 icao24,1 callsign,2 origin_country,
    # 5 lon,6 lat,7 baro_alt,8 on_ground,9 velocity,10 true_track,13 geo_alt.
    s = [None] * 17
    s[0] = "ab1644"
    s[1] = "UAL1091 "  # trailing space, like the API
    s[2] = "United States"
    s[5] = -96.42
    s[6] = 29.33
    s[7] = 6500.0
    s[8] = False
    s[9] = 209.6
    s[10] = 43.6
    s[13] = 6606.5
    return s


def test_parse_state_vector_maps_contract_shape():
    parsed = opensky.parse_state_vector(_sample_state())
    assert parsed == {
        "icao24": "ab1644",
        "callsign": "UAL1091",  # stripped
        "lat": 29.33,
        "lon": -96.42,
        "altitude": 6606.5,  # prefers geometric altitude
        "velocity": 209.6,
        "heading": 43.6,
        "on_ground": False,
    }


def test_parse_state_vector_falls_back_to_baro_altitude():
    s = _sample_state()
    s[13] = None  # no geo altitude
    parsed = opensky.parse_state_vector(s)
    assert parsed["altitude"] == 6500.0


def test_parse_state_vector_drops_positionless():
    s = _sample_state()
    s[5] = None
    s[6] = None
    assert opensky.parse_state_vector(s) is None


def test_parse_states_payload_skips_bad_entries():
    good = _sample_state()
    bad = _sample_state()
    bad[5] = None
    bad[6] = None
    out = opensky.parse_states_payload({"states": [good, bad]})
    assert len(out) == 1
    assert out[0]["icao24"] == "ab1644"


def test_get_access_token_returns_none_without_creds(settings):
    # No creds -> anonymous fallback, no crash, returns None.
    assert opensky.get_access_token(settings) is None


def test_fetch_snapshot_shape(settings, monkeypatch):
    monkeypatch.setattr(opensky, "get_access_token", lambda s: None)

    class _Resp:
        def json(self):
            return {"time": 1781639355, "states": [_sample_state()]}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(opensky, "make_client", lambda s, **k: _Client())
    monkeypatch.setattr(opensky, "get_with_retry", lambda *a, **k: _Resp())

    snap = opensky.fetch_snapshot(settings)
    assert snap["count"] == 1
    assert snap["as_of"] == 1781639355
    assert set(snap) == {"as_of", "stale_seconds", "source", "count", "aircraft"}
    assert snap["aircraft"][0]["callsign"] == "UAL1091"
