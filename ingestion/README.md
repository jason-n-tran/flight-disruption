# flight_ingest

Ingestion layer for the **Flight Disruption Intelligence Platform**. Pulls the
four raw sources into the **bronze** lake layer as parquet. Downstream
(`lakehouse/`, `dbt/`, `ml/`) reads bronze and enforces the model leakage
contract; this layer just lands clean, conformed raw data.

All bronze paths come from `flight_contracts.paths()`; all column / feature /
leakage lists come from `flight_contracts` and are never redefined here.

## What it produces

| Source       | Module           | Bronze output                              |
|--------------|------------------|--------------------------------------------|
| BTS On-Time  | `bts.py`         | `bronze/bts_ontime` (partitioned year/month) |
| Open-Meteo   | `weather.py`     | `bronze/weather_hourly` (partitioned iata) |
| OpenFlights  | `openflights.py` | `bronze/airports` (single parquet)         |
| OpenSky      | `opensky.py`     | sample JSON / backfill (no bronze table)   |

## Install

```bash
cd ingestion
uv sync                 # installs deps + flight-contracts (path dep ../shared)
# or, plain pip:
pip install -e ../shared -e .
```

Python >= 3.11 (tested on 3.12).

## Run

```bash
# Airport dimension first (weather needs lat/lon from it):
python -m flight_ingest.cli airports

# BTS months (defaults to BRONZE_YEARS x all 12 months; resumable):
python -m flight_ingest.cli bts --years 2022,2023,2024,2025
python -m flight_ingest.cli bts --years 2024 --months 1,2,3

# Open-Meteo archive, one call per airport over the bronze date range:
python -m flight_ingest.cli weather --years 2022,2023,2024,2025

# One-shot OpenSky snapshot for the bundled sample:
python -m flight_ingest.cli opensky-snapshot --out ./data/samples/live_positions_sample.json

# Everything in dependency order:
python -m flight_ingest.cli all --years 2022,2023,2024,2025
```

Add `--overwrite` to re-ingest existing partitions, `-v` for debug logging.

## Configuration

Copy `.env.example` to `.env`. Key vars:

- `LAKE_ROOT` — bronze/silver/gold root (shared contract).
- `INGEST_DATA_DIR` — raw-download cache (resumability).
- `INGEST_SSL_VERIFY` — see SSL note below.
- `OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` — optional; blank => anonymous.

The CLI reads `os.environ`; load your `.env` however you prefer (`uv run --env-file`,
`set -a; . .env`, direnv, etc.).

## SSL proxy note (dev machine only)

This particular Windows dev machine sits behind a corporate SSL proxy that
breaks Python's certificate verification (and curl revocation checks). The
**shipped code uses `httpx` with verification ON by default** — production has no
such proxy. For a live run on the affected machine, set the documented escape
hatch `INGEST_SSL_VERIFY=false`. For ad-hoc manual probing of a URL on that
machine, use `curl --ssl-no-revoke`. Do **not** disable verification in
production.

## Empirically-verified source facts (build is calibrated to these)

- **BTS**: direct PREZIP ZIP per month
  (`On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip`),
  ~27 MB, one CSV (110 cols, ~547K rows/mo) + readme.html. CSV filename has
  spaces+parens. `Accept-Ranges: bytes` (resumable). Harmless f5 cookie set.
- **Open-Meteo archive**: free, no key. ONE call returns the full multi-year
  hourly series per location (~4yr = 35064 hours, ~1.5 MB, ~6s). `visibility` is
  **NULL on archive** — never requested (`weather.py` asserts this). We use
  exactly `WEATHER_ARCHIVE_VARS`.
- **OpenSky**: `states/all` over the US bbox costs 4 credits/call; anon = 400/day,
  authenticated = 4000/day. OAuth2 client-credentials -> bearer token. This layer
  only does a one-shot snapshot — the continuous polling daemon is owned by
  `streaming/`.
- **OpenFlights**: `airports.dat` (headerless, 1.1 MB). Filter `country ==
  "United States"` and valid 3-letter IATA (excluding the `\N` sentinel). IATA
  join to BTS ≈ 97.3%; misses are US territories outside the bbox (dropped). A
  small patch dict fills known-missing continental codes (e.g. `XWA`).

## Tests

```bash
pytest                  # all HTTP is mocked; no network access
```

Covers: BTS column selection drops banned cols & keeps the label; OpenFlights
US/IATA filtering + patch; OpenSky state-vector parsing; weather never requests
`visibility`.
