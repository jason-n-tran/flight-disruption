"""BTS ingestion tests: column selection, leakage guard, snake_case, parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from flight_contracts import BANNED_LEAKY_COLUMNS
from flight_contracts.contract import LABEL_COLUMN
from flight_ingest import bts


def test_read_bts_zip_selects_keeps_and_drops_banned(fake_bts_zip, banned_columns):
    df = bts.read_bts_zip(fake_bts_zip)

    # Label survives.
    assert LABEL_COLUMN in df.columns

    # No NEW leaky column leaks through (DepDelay/WheelsOff were extras in the raw
    # file and are not in BTS_KEEP_COLUMNS -> must be absent).
    assert "dep_delay" not in df.columns
    assert "wheels_off" not in df.columns

    # The intentionally-kept-for-dashboards leaky cols (per contract) DO remain.
    assert "dep_delay_minutes" in df.columns  # DepDelayMinutes is in keep list

    # Trailing junk column dropped.
    assert not any(c.lower().startswith("unnamed") for c in df.columns)

    # Two rows preserved.
    assert len(df) == 2


def test_no_banned_col_outside_allowed_dashboard_set():
    # Every banned col present in the snake_cased output must have been an
    # explicitly-allowed dashboard column (intersection of banned & keep list).
    df_cols = {
        bts.COLUMN_RENAME.get(c, bts.snake_case(c))
        for c in __import__("flight_contracts").BTS_KEEP_COLUMNS
    }
    banned_snake = {bts.COLUMN_RENAME.get(c, bts.snake_case(c)) for c in BANNED_LEAKY_COLUMNS}
    allowed = banned_snake & df_cols
    # These are the leaky-but-kept dashboard columns; anything beyond is a bug.
    expected_allowed = {
        "dep_delay_minutes",
        "arr_del15",
        "cancelled",
        "diverted",
        "carrier_delay",
        "weather_delay",
        "nas_delay",
        "security_delay",
        "late_aircraft_delay",
    }
    assert allowed == expected_allowed


def test_enforce_schema_stable_across_nulls():
    """A column with nulls in one 'month' must keep the SAME parquet dtype as a
    month without nulls — otherwise Spark fails merging (int vs double)."""
    no_null = bts.enforce_schema(pd.DataFrame({"crs_elapsed_time": [90, 120]}))
    with_null = bts.enforce_schema(pd.DataFrame({"crs_elapsed_time": [90, None]}))
    assert str(no_null["crs_elapsed_time"].dtype) == "Int64"
    assert str(with_null["crs_elapsed_time"].dtype) == "Int64"  # not float64
    # flight number is stabilized as string (stable + matches silver cast)
    fn = bts.enforce_schema(pd.DataFrame({"flight_number_reporting_airline": [1, None]}))
    assert str(fn["flight_number_reporting_airline"].dtype) == "string"


def test_reschema_existing_rewrites_drifted_partition(settings, tmp_path):
    """A pre-existing partition with a drifted (float) int column is rewritten to
    the stable Int64 schema; idempotent on a second pass."""
    base = Path(settings.paths.bronze_table(bts.BRONZE_TABLE))
    pdir = base / "year=2024" / "month=8"
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / "data.parquet"
    # Simulate the August drift: crs_elapsed_time written as float due to a null.
    pd.DataFrame({"crs_elapsed_time": [90.0, None, 150.0],
                  "origin": ["ATL", "JFK", "LAX"]}).to_parquet(f, index=False)

    n = bts.reschema_existing(settings)
    assert n == 1
    fixed = pd.read_parquet(f)
    assert str(fixed["crs_elapsed_time"].dtype) == "Int64"


def test_snake_case_examples():
    assert bts.snake_case("DepDel15") == "dep_del15"
    assert bts.snake_case("Reporting_Airline") == "reporting_airline"
    assert bts.snake_case("CRSElapsedTime") == "crs_elapsed_time"


def test_ingest_month_writes_partition_and_is_resumable(settings, fake_bts_zip, monkeypatch):
    # Mock the network download to return our fake zip.
    monkeypatch.setattr(bts, "download_month", lambda *a, **k: fake_bts_zip)

    pdir = bts.ingest_month(settings, 2024, 3)
    assert pdir is not None
    assert (Path(pdir) / "data.parquet").exists()
    assert Path(pdir).as_posix().endswith("bts_ontime/year=2024/month=3")

    written = pd.read_parquet(Path(pdir) / "data.parquet")
    assert len(written) == 2

    # Second call skips (resumable / idempotent).
    assert bts.ingest_month(settings, 2024, 3) is None
