"""BTS On-Time Performance ingestion.

Downloads monthly PREZIP archives, extracts the single CSV in memory, selects
``BTS_KEEP_COLUMNS``, snake_cases the names, and writes year/month-partitioned
parquet to ``bronze/bts_ontime``. Resumable: an existing partition is skipped.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import pandas as pd

from flight_contracts import BANNED_LEAKY_COLUMNS, BTS_KEEP_COLUMNS, BRONZE_YEARS
from flight_contracts.contract import LABEL_COLUMN

from ._http import get_with_retry, make_client
from .config import BTS_URL_TEMPLATE, Settings

log = logging.getLogger("flight_ingest.bts")

BRONZE_TABLE = "bts_ontime"

# The model contract is enforced downstream (silver/gold), but bronze must never
# introduce a *new* leaky column beyond the curated dashboard set. These are the
# leaky-but-kept-for-dashboards columns explicitly allowed by BTS_KEEP_COLUMNS.
_ALLOWED_LEAKY_IN_BRONZE = set(BANNED_LEAKY_COLUMNS) & set(BTS_KEEP_COLUMNS)


def snake_case(name: str) -> str:
    """Convert a BTS column name (CamelCase / Mixed_Case) to snake_case.

    ``DepDel15`` -> ``dep_del15``; ``Flight_Number_Reporting_Airline`` ->
    ``flight_number_reporting_airline``; ``DayofMonth`` -> ``dayof_month``...
    we normalize the few known irregulars explicitly so join keys are stable.
    """
    s = name.strip()
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = s.replace("-", "_")
    s = re.sub(r"_+", "_", s)
    return s.lower()


# Stable, hand-verified rename map for the kept columns (avoids surprises from
# the generic snake_caser on oddballs like "DayofMonth").
COLUMN_RENAME: dict[str, str] = {
    "Year": "year",
    "Month": "month",
    "DayofMonth": "day_of_month",
    "DayOfWeek": "day_of_week",
    "FlightDate": "flight_date",
    "Reporting_Airline": "reporting_airline",
    "Flight_Number_Reporting_Airline": "flight_number_reporting_airline",
    "Origin": "origin",
    "Dest": "dest",
    "Distance": "distance",
    "CRSDepTime": "crs_dep_time",
    "CRSArrTime": "crs_arr_time",
    "CRSElapsedTime": "crs_elapsed_time",
    "DepDel15": "dep_del15",
    "DepDelayMinutes": "dep_delay_minutes",
    "ArrDel15": "arr_del15",
    "Cancelled": "cancelled",
    "Diverted": "diverted",
    "CarrierDelay": "carrier_delay",
    "WeatherDelay": "weather_delay",
    "NASDelay": "nas_delay",
    "SecurityDelay": "security_delay",
    "LateAircraftDelay": "late_aircraft_delay",
}


# Stable parquet dtypes for the (snake_cased) kept columns. Without this, pandas
# infers per-file — a month with null flight numbers becomes float64 while others
# are int64, and Spark's reader then fails merging across months with
# "Parquet column cannot be converted ... Expected bigint, Found DOUBLE".
# Nullable integer columns use pandas "Int64" (capital I) so nulls survive as
# bigint rather than promoting the whole column to double.
_STRING_COLS = ("flight_date", "reporting_airline", "flight_number_reporting_airline",
                "origin", "dest")
_INT_COLS = ("year", "month", "day_of_month", "day_of_week", "crs_dep_time",
             "crs_arr_time", "crs_elapsed_time", "distance", "dep_del15",
             "arr_del15", "cancelled", "diverted")
_FLOAT_COLS = ("dep_delay_minutes", "carrier_delay", "weather_delay", "nas_delay",
               "security_delay", "late_aircraft_delay")


def enforce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce kept columns to a STABLE dtype so every month's parquet matches.

    Strings -> pandas string; integer-like -> nullable Int64 (nulls stay bigint,
    not promoted to double); delay magnitudes -> float64. Idempotent.
    """
    for c in _STRING_COLS:
        if c in df.columns:
            df[c] = df[c].astype("string")
    for c in _INT_COLS:
        if c in df.columns:
            # to_numeric handles stray blanks/strings -> NaN, then nullable Int64
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in _FLOAT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df


def _validate_no_new_leakage() -> None:
    """Guard: kept columns must not smuggle a banned col beyond the allowed set."""
    kept = set(BTS_KEEP_COLUMNS)
    new_leaks = (kept & set(BANNED_LEAKY_COLUMNS)) - _ALLOWED_LEAKY_IN_BRONZE
    assert not new_leaks, f"Unexpected leaky columns in BTS_KEEP_COLUMNS: {new_leaks}"
    assert LABEL_COLUMN in {COLUMN_RENAME.get(c, snake_case(c)) for c in kept}, (
        "Label column missing from kept BTS columns"
    )


def select_and_rename(df: pd.DataFrame) -> pd.DataFrame:
    """Select kept columns from a raw BTS frame and snake_case them.

    Robust to the readme/trailing unnamed column the BTS CSV sometimes carries.
    """
    _validate_no_new_leakage()
    present = [c for c in BTS_KEEP_COLUMNS if c in df.columns]
    missing = [c for c in BTS_KEEP_COLUMNS if c not in df.columns]
    if missing:
        log.warning("BTS file missing expected columns (kept what exists): %s", missing)
    out = df[present].copy()
    out = out.rename(columns={c: COLUMN_RENAME.get(c, snake_case(c)) for c in present})
    return enforce_schema(out)


def _csv_member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError("No CSV member found in BTS zip")
    # The CSV filename has spaces+parens; the readme is .html. Take the CSV.
    return names[0]


def read_bts_zip(raw: bytes) -> pd.DataFrame:
    """Extract the CSV from BTS zip bytes and return the selected/renamed frame."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        member = _csv_member(zf)
        with zf.open(member) as fh:
            # BTS CSV is latin-1 / cp1252 friendly; low_memory off for mixed types.
            df = pd.read_csv(fh, encoding="latin-1", low_memory=False)
    return select_and_rename(df)


def _partition_dir(settings: Settings, year: int, month: int) -> Path:
    base = Path(settings.paths.bronze_table(BRONZE_TABLE))
    return base / f"year={year}" / f"month={month}"


def _partition_exists(settings: Settings, year: int, month: int) -> bool:
    pdir = _partition_dir(settings, year, month)
    return pdir.exists() and any(pdir.glob("*.parquet"))
