# flight_lakehouse — PySpark medallion (bronze → silver → gold)

The batch "brain" of the Flight Disruption Intelligence Platform. Takes the
bronze parquet produced by `ingestion/` and conforms + feature-engineers it into
a **leakage-safe** per-flight ML feature table plus dimension/aggregate-ready
tables, landed in DuckDB for `dbt/` and the serving layer.

Single-node PySpark, tuned for a 16GB workstation. Plain Parquet by default
(Delta optional, off behind an env flag) so a bare `pip install pyspark` works.

## Stages

| Stage | Module | Output |
|-------|--------|--------|
| **silver** | `silver.py` | `silver/flights`, `silver/airports`, `silver/weather` |
| **gold**   | `gold_features.py` | `gold/fct_flight_features` (parquet, partitioned by `year`) |
| **duckdb** | `to_duckdb.py` | registers gold + dim into the DuckDB file |

### Silver
Cleans + conforms BTS: filters to scheduled flights with valid origin/dest (in
the airports dim) and a non-null label; derives `dep_hour`,
`time_of_day_bucket`, a real `flight_ts`, and `is_holiday_window` (±2 days of a
US federal holiday). It **keeps dashboard-only columns** (delay minutes,
cancelled, diverted, cause columns) for the dbt agg marts — these are dropped
before the model feature table so they can never leak. Airports and weather are
conformed (weather `time` parsed to a timestamp + an integer hour key).

### Gold — the leakage-sensitive part
`gold/fct_flight_features` contains **exactly**
`MODEL_FEATURES + [dep_del15] + identity cols` (the build *asserts* this and
that no `BANNED_LEAKY_COLUMNS` snuck in).

#### Leakage-safe rolling reliability (portfolio talking point)
`route_hist_delay_rate`, `origin_hist_delay_rate`, and `carrier_hist_delay_rate`
are the mean of the label over flights that departed **strictly before** the
current flight's date. We aggregate the label to a per-entity-per-day
(count, sum), then take a cumulative count/sum over a day-ordered window with
`rangeBetween(unboundedPreceding, -1)` — the `-1` upper bound is what makes the
window **exclusive of the current day** (and thus all future days too). The rate
is `prior_sum / prior_count`; rows with no prior history (cold start) get the
global historical rate as a neutral fill. Two flights on the same day therefore
share a history-only value and neither sees the other → no same-day leakage.

#### Weather
Each flight is joined to the weather row at its airport for the **scheduled
departure hour** (`flight_date + dep_hour`), at both ORIGIN and DEST (DEST uses
the same scheduled hour — a documented simplification). Missing weather falls
back to sensible defaults (0 for precip/snow, mild constants for temp/wind).
`visibility` is intentionally excluded (null on the Open-Meteo archive).

## Run locally

```bash
# from lakehouse/
pip install -e ../shared -e .
# (bronze must already exist under $LAKE_ROOT — produce it with `flight-ingest`)
export LAKE_ROOT=./data/lake DUCKDB_PATH=./data/lake/gold.duckdb
python -m flight_lakehouse.run --stage all      # silver -> gold -> duckdb
# or a single stage:
python -m flight_lakehouse.run --stage silver
python -m flight_lakehouse.run --stage gold
python -m flight_lakehouse.run --stage duckdb
```

Requires a JVM on PATH (Java 8/11/17) for Spark.

### Windows notes
- Spark's native local-FS IO needs `winutils.exe` + a matching `hadoop.dll` in
  `%HADOOP_HOME%\bin`. If a `~\hadoop\bin\winutils.exe` install is present, the
  session builder auto-wires `HADOOP_HOME` + PATH for you.
- Set `SPARK_ARROW_ENABLED=0` if the Python worker crashes (some Windows +
  Python 3.12 + pyarrow combos are incompatible with Spark 3.5's Arrow path).
  The medallion itself uses only JVM operators (no Python UDFs), so it runs
  fine with Arrow off.

### Delta (optional, off by default)
```bash
pip install -e ".[delta]"
LAKE_FORMAT=delta python -m flight_lakehouse.run --stage all
```

## Docker
Built by the root compose `lake-builder` service (context = repo root, so it
copies `shared/ ingestion/ lakehouse/`). It can run ingestion then the medallion
in one image.

```bash
docker compose --profile pipeline run --rm lake-builder \
  python3 -m flight_lakehouse.run --stage all
```

## Tests
```bash
pip install -e ../shared -e ".[dev]"
python -m pytest -q
```
Tests build a tiny synthetic bronze, run silver + gold on a `local[2]` Spark
session, and assert the leakage-safe rolling feature equals the mean over
strictly-earlier flights, the contract column set is exact, no banned columns
leak, and the `dep_hour` / `time_of_day_bucket` derivations are correct. They
need a JVM installed and are slower than unit tests.
