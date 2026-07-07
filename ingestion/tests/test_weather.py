"""Weather ingestion tests: visibility never requested, archive parsing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from flight_contracts import WEATHER_ARCHIVE_VARS
from flight_ingest import weather


def test_visibility_never_requested():
    params = weather.build_archive_params(33.6, -84.4, "2022-01-01", "2025-12-31")
    hourly = params["hourly"].split(",")
    assert "visibility" not in hourly
    assert hourly == list(WEATHER_ARCHIVE_VARS)
    assert params["timezone"] == "UTC"


def test_build_params_asserts_if_visibility_sneaks_in(monkeypatch):
    # Even if the var list were corrupted to include visibility, the guard fires.
    monkeypatch.setattr(weather, "WEATHER_ARCHIVE_VARS", [*WEATHER_ARCHIVE_VARS, "visibility"])
    with pytest.raises(AssertionError):
        weather.build_archive_params(0.0, 0.0, "2022-01-01", "2022-12-31")


def test_parse_archive_response_uses_microsecond_time():
    """Spark 3.5 rejects Parquet TIMESTAMP(NANOS); time must be us precision."""
    payload = {"hourly": {
        "time": ["2022-01-01T00:00", "2022-01-01T01:00"],
        "temperature_2m": [1.0, 2.0], "precipitation": [0.0, 0.1],
        "wind_speed_10m": [5.0, 6.0], "wind_gusts_10m": [9.0, 10.0],
        "snowfall": [0.0, 0.0]}}
    df = weather.parse_archive_response("ATL", payload)
    assert getattr(df["time"].dtype, "unit", None) == "us"


def test_repair_timestamp_precision_rewrites_ns(settings, tmp_path):
    """A pre-existing ns-timestamp parquet is rewritten to us; us files untouched."""
    import pandas as pd
    base = settings.paths.bronze_table("weather_hourly")
    from pathlib import Path
    d = Path(base) / "iata=ATL"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "data.parquet"
    # write a deliberately-ns file (the old bug)
    bad = pd.DataFrame({"iata": "ATL",
                        "time": pd.to_datetime(["2022-01-01T00:00"], utc=True),
                        "temperature_2m": [1.0]})
    assert bad["time"].dtype.unit == "ns"
    bad.to_parquet(f, index=False)

    n = weather.repair_timestamp_precision(settings)
    assert n == 1
    fixed = pd.read_parquet(f)
    assert fixed["time"].dtype.unit == "us"

    # idempotent: a second pass repairs nothing
    assert weather.repair_timestamp_precision(settings) == 0


def test_parse_archive_response_tidy_frame():
    payload = {
        "hourly": {
            "time": ["2022-01-01T00:00", "2022-01-01T01:00"],
            "temperature_2m": [1.0, 2.0],
            "precipitation": [0.0, 0.1],
            "wind_speed_10m": [5.0, 6.0],
            "wind_gusts_10m": [9.0, 10.0],
            "snowfall": [0.0, 0.0],
        }
    }
    df = weather.parse_archive_response("ATL", payload)
    assert list(df.columns) == ["iata", "time", *WEATHER_ARCHIVE_VARS]
    assert "visibility" not in df.columns
    assert len(df) == 2
    assert (df["iata"] == "ATL").all()
    assert str(df["time"].dtype).startswith("datetime64")


def test_ingest_writes_partition_and_skips(settings, monkeypatch):
    airports = pd.DataFrame(
        [{"iata": "ATL", "lat": 33.6, "lon": -84.4}]
    )

    def _fake_fetch(s, client, iata, lat, lon, start, end):
        return weather.parse_archive_response(
            iata,
            {
                "hourly": {
                    "time": ["2022-01-01T00:00"],
                    "temperature_2m": [1.0],
                    "precipitation": [0.0],
                    "wind_speed_10m": [5.0],
                    "wind_gusts_10m": [9.0],
                    "snowfall": [0.0],
                }
            },
        )

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(weather, "make_client", lambda s, **k: _Client())
    monkeypatch.setattr(weather, "fetch_airport", _fake_fetch)

    written = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert len(written) == 1
    assert Path(written[0]).exists()
    assert Path(written[0]).as_posix().endswith("weather_hourly/iata=ATL/data.parquet")

    # Resumable: rerun skips.
    written2 = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert written2 == []


def test_airports_in_bts_scopes_and_ranks(settings):
    """Weather scope = only airports present in bronze BTS, ranked by volume,
    optionally capped to top_n. Guards the Open-Meteo rate-limit fix."""
    # Write a tiny bronze BTS partition: ATL appears 3x, ORD 2x, JFK 1x; SEA absent.
    bts_dir = Path(settings.paths.bronze_table("bts_ontime")) / "year=2024" / "month=1"
    bts_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "origin": ["ATL", "ATL", "ORD", "JFK"],
            "dest": ["ORD", "ATL", "ATL", "ATL"],
        }
    ).to_parquet(bts_dir / "data.parquet", index=False)

    airports = pd.DataFrame(
        [
            {"iata": "ATL", "lat": 33.6, "lon": -84.4},
            {"iata": "ORD", "lat": 41.9, "lon": -87.9},
            {"iata": "JFK", "lat": 40.6, "lon": -73.7},
            {"iata": "SEA", "lat": 47.4, "lon": -122.3},  # not in BTS -> dropped
        ]
    )

    scoped = weather.airports_in_bts(settings, airports)
    assert set(scoped["iata"]) == {"ATL", "ORD", "JFK"}  # SEA excluded
    assert scoped.iloc[0]["iata"] == "ATL"  # busiest first

    top1 = weather.airports_in_bts(settings, airports, top_n=1)
    assert list(top1["iata"]) == ["ATL"]


def test_airports_in_bts_falls_back_without_bronze(settings):
    """No bronze BTS yet -> return the full airport list (with a warning)."""
    airports = pd.DataFrame([{"iata": "ATL", "lat": 33.6, "lon": -84.4}])
    out = weather.airports_in_bts(settings, airports)
    assert list(out["iata"]) == ["ATL"]


def _ok_fetch(s, client, iata, lat, lon, start, end):
    return weather.parse_archive_response(iata, {"hourly": {
        "time": ["2022-01-01T00:00"], "temperature_2m": [1.0], "precipitation": [0.0],
        "wind_speed_10m": [5.0], "wind_gusts_10m": [9.0], "snowfall": [0.0]}})


class _NoCtxClient:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_weather_daily_budget_stops_cleanly(settings, monkeypatch):
    """Stops at the daily budget and leaves the rest for a resume (free-tier
    quota guard — the backfill spans multiple days by design)."""
    import dataclasses
    settings = dataclasses.replace(settings, weather_daily_budget=2)
    airports = pd.DataFrame([{"iata": c, "lat": 1.0, "lon": 2.0}
                             for c in ["AAA", "BBB", "CCC", "DDD"]])
    monkeypatch.setattr(weather, "make_client", lambda s, **k: _NoCtxClient())
    monkeypatch.setattr(weather, "fetch_airport", _ok_fetch)

    written = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert len(written) == 2  # stopped at budget, didn't fetch all 4

    # Resume: next run skips the 2 already written and does the next 2.
    written2 = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert len(written2) == 2
    # Third run: all done.
    assert weather.ingest(settings, airports, years=[2022], scope_to_bts=False) == []


def test_weather_circuit_breaker_on_consecutive_429(settings, monkeypatch):
    """If the daily quota is already spent (back-to-back 429s), abort fast
    instead of grinding through every airport x retries."""
    import dataclasses
    settings = dataclasses.replace(settings, weather_quota_abort_after=3,
                                   weather_daily_budget=100)
    airports = pd.DataFrame([{"iata": c, "lat": 1.0, "lon": 2.0}
                             for c in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]])
    calls = {"n": 0}

    def _always_429(s, client, iata, lat, lon, start, end):
        calls["n"] += 1
        raise RuntimeError("retryable status 429")

    monkeypatch.setattr(weather, "make_client", lambda s, **k: _NoCtxClient())
    monkeypatch.setattr(weather, "fetch_airport", _always_429)

    written = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert written == []
    assert calls["n"] == 3  # aborted after 3 consecutive failures, not all 6
    # And it left a cooldown marker so the next run won't spam.
    assert weather._cooldown_active(settings) is not None


def test_cooldown_skips_when_probe_still_limited(settings, monkeypatch):
    """With a cooldown active, a failing probe -> skip the stage cleanly (no
    per-airport spam), returning nothing."""
    import dataclasses
    settings = dataclasses.replace(settings, weather_quota_abort_after=3)
    airports = pd.DataFrame([{"iata": c, "lat": 1.0, "lon": 2.0}
                             for c in ["AAA", "BBB"]])
    weather._write_cooldown(settings, remaining=2)

    monkeypatch.setattr(weather, "_probe_quota", lambda *a, **k: False)
    # fetch_airport must NEVER be called when the probe says still-limited.
    monkeypatch.setattr(weather, "fetch_airport",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spammed!")))

    written = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert written == []


def test_cooldown_clears_when_probe_succeeds(settings, monkeypatch):
    """A successful probe clears the cooldown and lets the backfill proceed."""
    import dataclasses
    settings = dataclasses.replace(settings, weather_daily_budget=100)
    airports = pd.DataFrame([{"iata": c, "lat": 1.0, "lon": 2.0}
                             for c in ["AAA", "BBB"]])
    weather._write_cooldown(settings, remaining=2)

    monkeypatch.setattr(weather, "_probe_quota", lambda *a, **k: True)
    monkeypatch.setattr(weather, "make_client", lambda s, **k: _NoCtxClient())
    monkeypatch.setattr(weather, "fetch_airport", _ok_fetch)

    written = weather.ingest(settings, airports, years=[2022], scope_to_bts=False)
    assert len(written) == 2
    assert weather._cooldown_active(settings) is None  # cleared
