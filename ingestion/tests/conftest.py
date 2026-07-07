"""Shared pytest fixtures. NO network access — everything here is synthetic."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from flight_contracts import BANNED_LEAKY_COLUMNS, BTS_KEEP_COLUMNS
from flight_ingest.config import Settings


@pytest.fixture()
def settings(tmp_path) -> Settings:
    """Settings pointed entirely at a tmp dir; verification on, no creds."""
    return Settings(
        lake_root=str(tmp_path / "lake"),
        data_dir=tmp_path / "raw",
        ssl_verify=True,
        http_timeout=10.0,
        request_pause_sec=0.0,
        weather_pause_sec=0.0,
        max_retries=1,
        max_backoff_sec=1.0,
        user_agent="test",
        opensky_client_id=None,
        opensky_client_secret=None,
    )


@pytest.fixture()
def fake_bts_zip() -> bytes:
    """A tiny in-memory BTS zip: a CSV (kept cols + extra leaky + junk) + readme.

    The CSV filename intentionally has spaces+parens like the real BTS file, and
    we add extra raw columns (including a banned one NOT in the keep list and a
    trailing unnamed column) to prove selection drops them.
    """
    # Two data rows. Include every kept column plus extras that must be dropped.
    columns = list(BTS_KEEP_COLUMNS) + ["DepDelay", "WheelsOff", "Unnamed: 109"]
    row1 = {c: 1 for c in columns}
    row1.update(
        {
            "Year": 2024,
            "Month": 3,
            "FlightDate": "2024-03-01",
            "Reporting_Airline": "DL",
            "Origin": "ATL",
            "Dest": "ORD",
            "DepDel15": 1.0,
        }
    )
    row2 = dict(row1)
    row2.update({"Origin": "JFK", "Dest": "LAX", "DepDel15": 0.0})
    df = pd.DataFrame([row1, row2], columns=columns)

    csv_bytes = df.to_csv(index=False).encode("latin-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2024_3 (1).csv",
            csv_bytes,
        )
        zf.writestr("readme.html", "<html>not a csv</html>")
    return buf.getvalue()


@pytest.fixture()
def fake_airports_dat() -> str:
    """A snippet of airports.dat: US valid, US invalid IATA, non-US, quoted name."""
    return (
        '1,"Hartsfield Jackson Atlanta Intl","Atlanta","United States","ATL","KATL",'
        "33.6367,-84.4281,1026,-5,A,\"America/New_York\",airport,OurAirports\n"
        # Non-US -> dropped
        '2,"Heathrow","London","United Kingdom","LHR","EGLL",51.4706,-0.4619,83,0,E,'
        '"Europe/London",airport,OurAirports\n'
        # US but \N IATA -> dropped
        '3,"Some Helipad","Nowhere","United States","\\N","K99",40.0,-100.0,0,-6,A,'
        '"America/Chicago",airport,OurAirports\n'
        # US, comma in city handled by quoting
        '4,"John F Kennedy Intl","New York","United States","JFK","KJFK",40.6398,'
        '-73.7789,13,-5,A,"America/New_York",airport,OurAirports\n'
        # US but 4-letter "IATA" -> dropped
        '5,"Weird","Town","United States","ABCD","KZZZ",30.0,-90.0,0,-6,A,'
        '"America/Chicago",airport,OurAirports\n'
    )


@pytest.fixture()
def banned_columns() -> list[str]:
    return list(BANNED_LEAKY_COLUMNS)
