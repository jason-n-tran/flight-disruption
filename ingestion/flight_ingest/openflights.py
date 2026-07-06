"""OpenFlights airport dimension ingestion.

Downloads ``airports.dat`` (headerless CSV), filters to US airports with a valid
3-letter IATA code, applies a small patch for known-missing continental codes,
and writes ``bronze/airports`` parquet (iata, name, city, lat, lon, tz).
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

import pandas as pd

from ._http import get_with_retry, make_client
from .config import OPENFLIGHTS_AIRPORTS_URL, Settings

log = logging.getLogger("flight_ingest.openflights")

BRONZE_TABLE = "airports"

# airports.dat column indices (no header in the file).
_IDX = {
    "id": 0,
    "name": 1,
    "city": 2,
    "country": 3,
    "iata": 4,
    "icao": 5,
    "lat": 6,
    "lon": 7,
    "alt": 8,
    "tz": 9,
}

# Null sentinel OpenFlights uses for missing fields.
_NULL_SENTINEL = "\\N"

# Continental-US airports BTS reports but OpenFlights misses/lags. Patch dict so
# the IATA join doesn't drop real flights. (iata -> name, city, lat, lon, tz)
PATCH: dict[str, dict[str, object]] = {
    "XWA": {
        "name": "Williston Basin International Airport",
        "city": "Williston",
        "lat": 48.2594,
        "lon": -103.7510,
        "tz": "America/Chicago",
    },
}


def _valid_iata(code: str) -> bool:
    return (
        isinstance(code, str)
        and len(code) == 3
        and code.isalpha()
        and code != _NULL_SENTINEL
    )


def parse_airports(text: str) -> pd.DataFrame:
    """Parse airports.dat text -> filtered US airport DataFrame.

    Quoted fields with embedded commas are handled by the csv reader.
    """
    rows: list[dict[str, object]] = []
    reader = csv.reader(io.StringIO(text))
    for fields in reader:
        if len(fields) <= _IDX["tz"]:
            continue
        if fields[_IDX["country"]] != "United States":
            continue
        iata = fields[_IDX["iata"]]
        if not _valid_iata(iata):
            continue
        try:
            lat = float(fields[_IDX["lat"]])
            lon = float(fields[_IDX["lon"]])
        except ValueError:
            continue
        tz = fields[_IDX["tz"]]
        rows.append(
            {
                "iata": iata,
                "name": fields[_IDX["name"]],
                "city": fields[_IDX["city"]],
                "lat": lat,
                "lon": lon,
                "tz": None if tz == _NULL_SENTINEL else tz,
            }
        )

    df = pd.DataFrame(rows, columns=["iata", "name", "city", "lat", "lon", "tz"])
    df = _apply_patch(df)
    df = df.drop_duplicates(subset="iata", keep="first").reset_index(drop=True)
    return df


def _apply_patch(df: pd.DataFrame) -> pd.DataFrame:
    existing = set(df["iata"])
    additions = [
        {"iata": code, **vals} for code, vals in PATCH.items() if code not in existing
    ]
    if additions:
        log.info("Patched %d missing airport(s): %s", len(additions),
                 [a["iata"] for a in additions])
        df = pd.concat([df, pd.DataFrame(additions)], ignore_index=True)
    return df


def download_airports(settings: Settings) -> str:
    """Download airports.dat, caching the raw file under ``data_dir``."""
    settings.ensure_dirs()
    cache_path = settings.data_dir / "airports.dat"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        log.info("Using cached airports.dat %s", cache_path)
        return cache_path.read_text(encoding="utf-8")
    log.info("Downloading airports.dat from %s", OPENFLIGHTS_AIRPORTS_URL)
    with make_client(settings) as client:
        resp = get_with_retry(
            client,
            OPENFLIGHTS_AIRPORTS_URL,
            max_retries=settings.max_retries,
            pause=settings.request_pause_sec,
        )
        text = resp.text
    cache_path.write_text(text, encoding="utf-8")
    return text


def ingest(settings: Settings, *, overwrite: bool = False) -> Path:
    """Ingest the airport dimension to ``bronze/airports``."""
    out_file = Path(settings.paths.bronze_table(BRONZE_TABLE)) / "data.parquet"
    if out_file.exists() and not overwrite:
        log.info("Skip airports (parquet exists at %s)", out_file)
        return out_file
    text = download_airports(settings)
    df = parse_airports(text)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_file, index=False)
    log.info("Wrote %s (%d US airports)", out_file, len(df))
    return out_file


def load_airports(settings: Settings) -> pd.DataFrame:
    """Read the bronze airport dim (ingesting first if absent)."""
    out_file = Path(settings.paths.bronze_table(BRONZE_TABLE)) / "data.parquet"
    if not out_file.exists():
        ingest(settings)
    return pd.read_parquet(out_file)
