"""Pytest fixtures: a local[2] Spark session + a tiny synthetic bronze lake.

The synthetic bronze is hand-constructed so the leakage-safe rolling feature is
checkable by hand (see test_gold_features.py for the arithmetic).
"""

from __future__ import annotations

import os
import sys

import pytest

# Pin worker python before Spark starts (Windows / mixed env).
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
# Arrow can crash the Python worker on Windows + py3.12 + pyarrow; use the
# stable pure-Python path for the test suite.
os.environ.setdefault("SPARK_ARROW_ENABLED", "0")

# On Windows, Spark's Hadoop native IO needs winutils.exe + hadoop.dll on
# HADOOP_HOME/bin (and on PATH). If a local install exists, wire it up so the
# Spark tests can do local-filesystem reads/writes. Harmless on non-Windows.
if os.name == "nt" and not os.environ.get("HADOOP_HOME"):
    _candidate = os.path.expanduser(r"~\hadoop")
    if os.path.exists(os.path.join(_candidate, "bin", "winutils.exe")):
        os.environ["HADOOP_HOME"] = _candidate
        os.environ["PATH"] = (
            os.path.join(_candidate, "bin") + os.pathsep + os.environ.get("PATH", "")
        )


@pytest.fixture(scope="session")
def spark():
    from flight_lakehouse.session import build_spark

    s = build_spark(app_name="flight-lakehouse-tests", master="local[2]")
    yield s
    s.stop()


def _write_parquet(df, path):
    import os as _os

    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    df.to_parquet(path, index=False)


@pytest.fixture()
def synthetic_lake(tmp_path, monkeypatch):
    """Create a tiny bronze lake under tmp_path and return its LakeConfig.

    Flights (all origin=AAA, carrier=ZZ, dest varies) across 3 dates:

      2024-01-10  : 2 flights, dep_del15 = [1, 1]
      2024-01-11  : 1 flight,  dep_del15 = [0]
      2024-01-12  : 1 flight,  dep_del15 = [0]   <-- the probe flight

    For the probe flight on 01-12, origin_hist_delay_rate must equal the mean of
    dep_del15 over STRICTLY earlier days = (1+1+0)/3 = 0.6667. The two 01-10
    flights are the earliest for AAA -> no prior -> global prior fill.
    """
    import pandas as pd

    from flight_contracts.contract import paths as contract_paths

    lake_root = str(tmp_path / "lake")

    p = contract_paths(lake_root)

    # --- airports ---
    airports = pd.DataFrame(
        {
            "iata": ["AAA", "BBB", "CCC"],
            "name": ["Alpha", "Bravo", "Charlie"],
            "city": ["A City", "B City", "C City"],
            "lat": [40.0, 41.0, 42.0],
            "lon": [-100.0, -101.0, -102.0],
            "tz": ["America/Chicago"] * 3,
        }
    )
    _write_parquet(airports, os.path.join(p.bronze_table("airports"), "airports.parquet"))

    # --- BTS flights ---
    # columns mirror the FIXED bronze schema (snake_case BTS_KEEP_COLUMNS).
    def flight(fd, dow, dep, dep15, dest, fnum, dist=300.0, elapsed=90.0):
        return {
            "year": 2024,
            "month": 1,
            "dayof_month": int(fd.split("-")[2]),
            "day_of_week": dow,
            "flight_date": fd,
            "reporting_airline": "ZZ",
            "flight_number_reporting_airline": fnum,
            "origin": "AAA",
            "dest": dest,
            "distance": dist,
            "crs_dep_time": dep,
            "crs_arr_time": dep + 130,
            "crs_elapsed_time": elapsed,
            "dep_del15": float(dep15),
            "dep_delay_minutes": 20.0 if dep15 else 0.0,
            "arr_del15": float(dep15),
            "cancelled": 0.0,
            "diverted": 0.0,
            "carrier_delay": 0.0,
            "weather_delay": 0.0,
            "nas_delay": 0.0,
            "security_delay": 0.0,
            "late_aircraft_delay": 0.0,
        }

    rows = [
        # 2024-01-10: two delayed flights (dep at 08:00 and 17:00).
        flight("2024-01-10", 3, 800, 1, "BBB", 1),
        flight("2024-01-10", 3, 1700, 1, "CCC", 2),
        # 2024-01-11: one on-time flight (dep at 09:00).
        flight("2024-01-11", 4, 900, 0, "BBB", 3),
        # 2024-01-12: the probe flight, on-time (dep at 14:30 -> hour 14).
        flight("2024-01-12", 5, 1430, 0, "BBB", 4),
    ]
    bts = pd.DataFrame(rows)
    # bronze is partitioned year=/month=; a single partition dir is enough for
    # Spark's reader (it discovers year/month as columns).
    bts_dir = os.path.join(p.bronze_table("bts_ontime"), "year=2024", "month=1")
    _write_parquet(
        bts.drop(columns=["year", "month"]),
        os.path.join(bts_dir, "part.parquet"),
    )

    # --- weather: one matching hour for the probe flight at AAA (hour 14) ---
    # `time` is a real MICROSECOND timestamp, matching what the ingester writes
    # (Spark 3.5 rejects ns) — exercises silver's timestamp-typed branch.
    weather = pd.DataFrame(
        {
            "iata": ["AAA"],
            "time": pd.to_datetime(["2024-01-12T14:00"], utc=True).astype("datetime64[us, UTC]"),
            "temperature_2m": [5.5],
            "precipitation": [1.2],
            "wind_speed_10m": [22.0],
            "wind_gusts_10m": [33.0],
            "snowfall": [0.4],
        }
    )
    _write_parquet(
        weather, os.path.join(p.bronze_table("weather_hourly"), "iata=AAA", "data.parquet")
    )

    monkeypatch.setenv("LAKE_ROOT", lake_root)
    monkeypatch.setenv("DUCKDB_PATH", os.path.join(lake_root, "gold.duckdb"))
    monkeypatch.setenv("LAKE_FORMAT", "parquet")

    from flight_lakehouse.config import load_config

    return load_config()
