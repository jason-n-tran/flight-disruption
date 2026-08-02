# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze: ingest raw sources into `flight.bronze.*`
# MAGIC
# MAGIC Lands the three raw sources as UC **managed Delta tables**, mirroring the
# MAGIC local ingestion layer (`ingestion/flight_ingest/`):
# MAGIC
# MAGIC | Bronze table              | Source                         | Grain                       |
# MAGIC |---------------------------|--------------------------------|-----------------------------|
# MAGIC | `bronze.bts_ontime`       | BTS On-Time Performance PREZIP | one row per scheduled flight |
# MAGIC | `bronze.weather_hourly`   | Open-Meteo archive             | one row per airport per hour |
# MAGIC | `bronze.airports`         | OpenFlights `airports.dat`     | one row per US IATA airport  |
# MAGIC
# MAGIC Bronze keeps the curated BTS column set (`BTS_KEEP_COLUMNS`), snake-cased —
# MAGIC **including** the leaky-but-dashboard-useful columns (delay minutes, cause
# MAGIC columns, cancelled/diverted). Those are carried through silver for the agg
# MAGIC marts and **dropped before the gold ML feature table** so they never reach
# MAGIC the model. (Same split as the local pipeline.)
# MAGIC
# MAGIC ## Three ingest paths (pick one)
# MAGIC
# MAGIC 1. **Pre-ingested parquet (fastest for portfolio demo):** if the local
# MAGIC    ingestion pipeline has already populated `data/lake/bronze/` with parquet
# MAGIC    files, use `parquet` mode — we read them directly.
# MAGIC 2. **UC Volume + CSVs (recommended on Free Edition):** upload raw files to
# MAGIC    `/Volumes/{catalog}/bronze/landing/` via Catalog Explorer:
# MAGIC    - BTS: unzip a PREZIP to get the CSV, or upload as `{year}_{month}.csv`
# MAGIC    - airports.dat from OpenFlights repo
# MAGIC    - weather: parquet dir from a prior local run, or export as CSV
# MAGIC 3. **Direct download:** if outbound HTTP works, fetch BTS PREZIP / OpenFlights
# MAGIC    / Open-Meteo directly (shows lineage to public sources).
# MAGIC
# MAGIC Set `SOURCE_MODE` below.

# COMMAND ----------

dbutils.widgets.text("catalog", "flight", "Unity Catalog name")
dbutils.widgets.dropdown(
    "source_mode",
    "parquet",
    ["parquet", "volume", "download"],
    "Source mode (parquet=existing local data, volume=UC Volume, download=fetch live)"
)
dbutils.widgets.text("parquet_path", "/Workspace/repos/flight-repo/data/lake/bronze", "Path to local bronze parquet (if source_mode=parquet)")
dbutils.widgets.text("years", "2024", "BTS years (comma-sep)")
dbutils.widgets.text("months", "1,2,3", "BTS months (comma-sep)")

CATALOG = dbutils.widgets.get("catalog")
SOURCE_MODE = dbutils.widgets.get("source_mode")
PARQUET_PATH = dbutils.widgets.get("parquet_path")
YEARS = [int(y) for y in dbutils.widgets.get("years").split(",") if y.strip()]
MONTHS = [int(m) for m in dbutils.widgets.get("months").split(",") if m.strip()]

VOLUME = f"/Volumes/{CATALOG}/bronze/landing"

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql("USE SCHEMA bronze")
print(f"catalog={CATALOG} mode={SOURCE_MODE} years={YEARS} months={MONTHS}")
if SOURCE_MODE == "parquet":
    print(f"parquet_path={PARQUET_PATH}")
else:
    print(f"volume={VOLUME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source constants (mirror `ingestion/flight_ingest/config.py`)

# COMMAND ----------

# BTS PREZIP: one ZIP per month. Each contains a single ~547K-row CSV (110 cols).
BTS_URL_TEMPLATE = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPENFLIGHTS_AIRPORTS_URL = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)

# Curated BTS columns (raw name -> snake_case), mirroring BTS_KEEP_COLUMNS +
# COLUMN_RENAME in the contract / ingestion. Pre-departure-safe + label + the
# dashboard-only (leaky) columns kept for the agg marts.
BTS_COLUMN_RENAME = {
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

# Open-Meteo archive vars — visibility EXCLUDED (null on archive).
WEATHER_ARCHIVE_VARS = [
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "snowfall",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## BTS On-Time → `bronze.bts_ontime`
# MAGIC
# MAGIC We read each month's CSV, keep + rename the curated columns, add
# MAGIC `year`/`month` partition columns, and append to a single Delta table.
# MAGIC
# MAGIC - **Volume mode:** expects the monthly CSV (or the unzipped CSV) at
# MAGIC   `{VOLUME}/bts/On_Time_..._{year}_{month}.csv`. The BTS ZIP contains one
# MAGIC   CSV; unzip locally and upload the CSV (Spark CSV reader is simplest), or
# MAGIC   upload the ZIP and unzip it in a Python cell (shown below).
# MAGIC - **Download mode:** fetches the PREZIP, unzips in the driver, writes CSV
# MAGIC   bytes to a temp path, then reads with Spark.
# MAGIC
# MAGIC The CSV carries 110 columns + a trailing unnamed column; we `select` only
# MAGIC the curated set, so extra columns are harmless.

# COMMAND ----------

import io
import zipfile

from pyspark.sql import functions as F
from pyspark.sql import types as T


def _read_bts_csv_spark(path: str):
    """Read a BTS CSV with Spark, keep + rename the curated columns."""
    raw = (
        spark.read.option("header", True)
        .option("inferSchema", True)
        .option("encoding", "latin-1")
        .csv(path)
    )
    present = [c for c in BTS_COLUMN_RENAME if c in raw.columns]
    missing = [c for c in BTS_COLUMN_RENAME if c not in raw.columns]
    if missing:
        print(f"  WARNING: BTS file missing columns (kept what exists): {missing}")
    out = raw.select(*[F.col(c).alias(BTS_COLUMN_RENAME[c]) for c in present])
    return out


def _download_bts_month_to_volume(year: int, month: int) -> str:
    """Download the BTS PREZIP, unzip the single CSV, stage it under the volume.

    Returns the staged CSV path. Requires outbound network (download mode).
    """
    import urllib.request

    url = BTS_URL_TEMPLATE.format(year=year, month=month)
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "flight-portfolio/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        raw = resp.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        csv_bytes = zf.read(member)
    # Stage to the UC volume so Spark can read it as a normal file path.
    staged = f"{VOLUME}/bts/{year}_{month:02d}.csv"
    dbutils.fs.mkdirs(f"{VOLUME}/bts")
    with open(staged, "wb") as fh:
        fh.write(csv_bytes)
    print(f"  staged -> {staged} ({len(csv_bytes):,} bytes)")
    return staged


def ingest_bts():
    if SOURCE_MODE == "parquet":
        # **Parquet mode:** read from the local ingestion pipeline's output
        print(f"BTS (parquet mode): reading from {PARQUET_PATH}/bts_ontime/")
        df = spark.read.parquet(f"{PARQUET_PATH}/bts_ontime/")
        (
            df.write.format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .partitionBy("year", "month")
            .saveAsTable(f"{CATALOG}.bronze.bts_ontime")
        )
        print(f"wrote bronze.bts_ontime ({df.count()} rows)")
        return

    # **Volume or download modes:** read from CSVs
    frames = []
    for y in YEARS:
        for m in MONTHS:
            if SOURCE_MODE == "download":
                path = _download_bts_month_to_volume(y, m)
            else:
                # Volume mode: expect a pre-uploaded CSV. Accept a couple of names.
                candidates = [
                    f"{VOLUME}/bts/{y}_{m:02d}.csv",
                    f"{VOLUME}/bts/On_Time_Reporting_Carrier_On_Time_Performance_"
                    f"1987_present_{y}_{m}.csv",
                ]
                path = next((p for p in candidates if _exists(p)), candidates[0])
            print(f"BTS {y}-{m:02d}: reading {path}")
            df = _read_bts_csv_spark(path)
            frames.append(df)

    if not frames:
        raise ValueError("No BTS months selected.")
    combined = frames[0]
    for f in frames[1:]:
        combined = combined.unionByName(f, allowMissingColumns=True)

    (
        combined.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .partitionBy("year", "month")
        .saveAsTable(f"{CATALOG}.bronze.bts_ontime")
    )
    print("wrote bronze.bts_ontime")
