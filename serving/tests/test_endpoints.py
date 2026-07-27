"""Contract-shape tests for every endpoint, against the bundled sample artifacts."""

from __future__ import annotations

import pytest

VALID_BANDS = {"low", "moderate", "high"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["gold_loaded"] is True
    assert body["data_version"] == "test-sample"


def test_meta_options(client):
    r = client.get("/api/meta/options")
    assert r.status_code == 200
    body = r.json()
    assert len(body["airports"]) > 0
    a = body["airports"][0]
    assert set(a) >= {"iata", "name", "lat", "lon"}
    assert len(body["carriers"]) > 0
    c = body["carriers"][0]
    assert set(c) >= {"code", "name"}
    assert len(body["example_presets"]) > 0
    p = body["example_presets"][0]
    assert set(p) >= {"origin", "dest", "carrier", "day_of_week", "dep_hour"}


def test_predict_shape_and_ranges(client):
    r = client.post(
        "/api/predict",
        json={"origin": "ATL", "dest": "ORD", "carrier": "DL",
              "date": "2026-06-20", "dep_hour": 17},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert 0.0 <= body["delay_probability"] <= 1.0
    assert body["risk_band"] in VALID_BANDS
    assert 0.0 <= body["baseline_probability"] <= 1.0
    assert isinstance(body["beats_baseline"], bool)
    assert body["calibrated"] is True

    assert isinstance(body["top_factors"], list)
    assert len(body["top_factors"]) >= 1
    f = body["top_factors"][0]
    assert set(f) >= {"feature", "value", "contribution", "direction"}
    assert f["direction"] in {"increases", "decreases"}

    ws = body["weather_summary"]
    assert set(ws["origin"]) >= {"temp_c", "precip_mm", "wind_gusts"}
    assert set(ws["dest"]) >= {"temp_c", "precip_mm", "wind_gusts"}
    assert body["data_version"] == "test-sample"


def test_predict_risk_band_matches_probability(client):
    r = client.post(
        "/api/predict",
        json={"origin": "SFO", "dest": "ATL", "carrier": "UA",
              "date": "2026-12-24", "dep_hour": 8},
    )
    assert r.status_code == 200
    body = r.json()
    p = body["delay_probability"]
    expected = "low" if p < 0.20 else ("moderate" if p < 0.45 else "high")
    assert body["risk_band"] == expected


def test_predict_unknown_route_still_works(client):
    # An origin/dest pair that may not be a known route should still score via
    # great-circle distance + baseline fallback (never 500).
    r = client.post(
        "/api/predict",
        json={"origin": "MIA", "dest": "BOS", "carrier": "AA",
              "date": "2026-07-01", "dep_hour": 14},
    )
    assert r.status_code == 200, r.text
    assert 0.0 <= r.json()["delay_probability"] <= 1.0


def test_live_positions_sample_fallback(client):
    r = client.get("/api/live/positions")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in {"live", "cached", "sample"}
    assert body["source"] == "sample"  # Valkey disabled in tests
    assert body["count"] > 0
    assert len(body["aircraft"]) == body["count"]
    ac = body["aircraft"][0]
    assert set(ac) >= {"icao24", "callsign", "lat", "lon", "altitude",
                       "velocity", "heading", "on_ground"}


def test_airport_bridge(client):
    r = client.get("/api/airport/ATL")
    assert r.status_code == 200
    body = r.json()
    assert body["iata"] == "ATL"
    assert "name" in body and "lat" in body and "lon" in body
    hist = body["historical"]
    assert "overall_delay_rate" in hist
    assert isinstance(hist["by_hour"], list)
    assert isinstance(hist["worst_routes"], list)
    cong = body["live_congestion"]
    assert "aircraft_nearby" in cong
    assert cong["level"] in {"low", "moderate", "high"}


def test_airport_unknown_404(client):
    r = client.get("/api/airport/ZZZ")
    assert r.status_code == 404


def test_reliability_route(client):
    r = client.get("/api/reliability/route", params={"origin": "ATL", "dest": "ORD"})
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "ATL"
    assert body["dest"] == "ORD"
    assert 0.0 <= body["delay_rate"] <= 1.0
    assert body["flights"] > 0
    assert isinstance(body["by_carrier"], list)


def test_reliability_route_unknown_404(client):
    r = client.get("/api/reliability/route", params={"origin": "AAA", "dest": "BBB"})
    assert r.status_code == 404
