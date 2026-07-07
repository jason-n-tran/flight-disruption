"""OpenFlights filtering tests: US + valid IATA, quoting, patch dict."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from flight_ingest import openflights


def test_parse_airports_filters_us_and_valid_iata(fake_airports_dat):
    df = openflights.parse_airports(fake_airports_dat)
    codes = set(df["iata"])

    # Kept: valid US 3-letter.
    assert "ATL" in codes
    assert "JFK" in codes

    # Dropped: non-US (LHR), \N sentinel, 4-letter ABCD.
    assert "LHR" not in codes
    assert "ABCD" not in codes
    assert "\\N" not in codes

    # Quoted city with no comma still parses; columns conform to schema.
    assert list(df.columns) == ["iata", "name", "city", "lat", "lon", "tz"]
    atl = df[df["iata"] == "ATL"].iloc[0]
    assert atl["city"] == "Atlanta"
    assert abs(atl["lat"] - 33.6367) < 1e-6


def test_patch_adds_missing_continental_code(fake_airports_dat):
    df = openflights.parse_airports(fake_airports_dat)
    # XWA is in the patch dict and not in the snippet -> must be added.
    assert "XWA" in set(df["iata"])
    xwa = df[df["iata"] == "XWA"].iloc[0]
    assert abs(xwa["lat"] - 48.2594) < 1e-6


def test_patch_does_not_duplicate_existing(monkeypatch, fake_airports_dat):
    # If ATL were in the patch dict it must not be duplicated.
    monkeypatch.setitem(
        openflights.PATCH,
        "ATL",
        {"name": "x", "city": "y", "lat": 0.0, "lon": 0.0, "tz": "Z"},
    )
    df = openflights.parse_airports(fake_airports_dat)
    assert (df["iata"] == "ATL").sum() == 1


def test_ingest_writes_parquet_and_skips(settings, fake_airports_dat, monkeypatch):
    monkeypatch.setattr(openflights, "download_airports", lambda s: fake_airports_dat)
    out = openflights.ingest(settings)
    assert Path(out).exists()
    df = pd.read_parquet(out)
    assert "ATL" in set(df["iata"])

    # Resumable: a second ingest without overwrite returns same path, no re-download.
    def _boom(_s):  # would fail if called
        raise AssertionError("should not re-download")

    monkeypatch.setattr(openflights, "download_airports", _boom)
    out2 = openflights.ingest(settings)
    assert Path(out2) == Path(out)
