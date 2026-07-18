# dbt-duckdb: Flight gold analytical marts

This dbt project turns the conformed **silver** layer produced by the PySpark
lakehouse into **tested, documented gold marts** materialised as tables inside a
DuckDB file. The FastAPI serving layer reads those tables directly, by name, to
answer the reliability / airport / route endpoints in
[`shared/flight_contracts/api_contract.md`](../../shared/flight_contracts/api_contract.md).

The gold table names are fixed by
[`shared/flight_contracts/contract.py`](../../shared/flight_contracts/contract.py)
and the serving layer reads them by those exact names — do not rename the mart
models.

## What it builds

```
sources (silver parquet)  OR  seeds (sample CSV)
        │
        ▼
staging/  stg_flights, stg_airports          (views, light typing/renaming)
        │
        ▼
marts/    dim_airports                        ← GOLD_AIRPORTS_DIM
          agg_route_reliability               ← GOLD_ROUTE_RELIABILITY
          agg_route_carrier_reliability       (by_carrier breakdown helper)
          agg_airport_reliability             ← GOLD_AIRPORT_RELIABILITY
          agg_airport_hourly                  (by_hour chart helper)
          agg_airport_worst_routes            (worst_routes helper, ranked)
          agg_carrier_reliability             ← GOLD_CARRIER_RELIABILITY
          agg_hourly_patterns                 ← GOLD_HOURLY_PATTERNS
```

All marts materialise as **tables** in the DuckDB `main` schema so they persist
for serving. Staging models are views; seeds land in a `seeds` schema.

### Mart → API endpoint mapping

| Mart table                       | Serving endpoint                                   |
| -------------------------------- | -------------------------------------------------- |
| `dim_airports`                   | `GET /api/meta/options`, header of `GET /api/airport/{iata}` |
| `agg_route_reliability`          | `GET /api/reliability/route` (scalar fields)       |
| `agg_route_carrier_reliability`  | `GET /api/reliability/route` (`by_carrier` list)   |
| `agg_airport_reliability`        | `GET /api/airport/{iata}` (`overall_delay_rate`)   |
| `agg_airport_hourly`             | `GET /api/airport/{iata}` (`by_hour`)              |
| `agg_airport_worst_routes`       | `GET /api/airport/{iata}` (`worst_routes`, take top N by `rnk`) |
| `agg_carrier_reliability`        | carrier reliability charts / BI                    |
| `agg_hourly_patterns`            | temporal-patterns chart (hour × day-of-week)       |

> `fct_flight_features` (`GOLD_FEATURES_TABLE`) is **not** built here. It is the
> per-flight ML feature table and is produced upstream by the PySpark lakehouse /
> ML pipeline (it needs weather joins and leakage-safe rolling history). dbt owns
> the aggregate reliability marts + the airport dimension; the ML feature row
> grain stays in the lakehouse.

## Environment variables

| Var                | Default                     | Purpose                                        |
| ------------------ | --------------------------- | ---------------------------------------------- |
| `LAKE_ROOT`        | `./data/lake`               | Root of the silver parquet (read when not using seeds). |
| `DUCKDB_PATH`      | `./data/lake/gold.duckdb`   | DuckDB file the marts are written to / served from. |
| `DBT_PROFILES_DIR` | (must set)                  | Point at this dir; the project ships its own `profiles.yml`. |

Copy `.env.example` to `.env` and adjust. Never commit `.env`.

## Run on the bundled seeds (no real lake needed — CI / local dev)

The real silver parquet does not exist in a fresh clone, so the project ships
~96 sample flights across 15 routes / 5 carriers / 8 hours / 8 dates and 12
airports. Build everything from seeds with `--vars 'use_seeds: true'`:

```bash
cd dbt/flight
export DBT_PROFILES_DIR="$(pwd)"
export DUCKDB_PATH="$(pwd)/target/gold.duckdb"   # any path you like

dbt seed  --vars 'use_seeds: true'
dbt run   --vars 'use_seeds: true'
dbt test  --vars 'use_seeds: true'
```

PowerShell:

```powershell
cd dbt\flight
$env:DBT_PROFILES_DIR = (Get-Location).Path
$env:DUCKDB_PATH = Join-Path (Get-Location).Path "target\gold.duckdb"
dbt seed --vars 'use_seeds: true'
dbt run  --vars 'use_seeds: true'
dbt test --vars 'use_seeds: true'
```

No `dbt deps` step is required — the project is self-contained (`packages.yml`
is empty; the `accepted_range` and `unique_combination` generic tests live in
`tests/generic/`, so it runs offline).

## Run against the real lake

Point `LAKE_ROOT` at the PySpark lakehouse output and `DUCKDB_PATH` at the
serving DuckDB file, then run **without** the seed toggle (`use_seeds` defaults
to `false`). Staging then reads silver parquet via DuckDB `read_parquet`:

```bash
export DBT_PROFILES_DIR="$(pwd)"
export LAKE_ROOT=/path/to/data/lake
export DUCKDB_PATH=/path/to/data/lake/gold.duckdb

dbt run     # builds marts from $LAKE_ROOT/silver/{flights,airports}/**/*.parquet
dbt test
```

Sources are defined in `models/staging/_sources.yml` and read
`$LAKE_ROOT/silver/<table>/**/*.parquet` with `hive_partitioning=true` and
`union_by_name=true`.

## How it feeds the demo

`DUCKDB_PATH` is the same file the FastAPI serving layer opens. After `dbt run`
the file contains the `dim_airports` / `agg_*` tables in `main`, queryable as
bare table names. A `generate_schema_name` macro override
(`macros/generate_schema_name.sql`) keeps marts in `main` (instead of dbt's
default `main_marts`) so the serving SQL stays unqualified.

## Tests

Every model has column/model descriptions. Tests include: `not_null` on all
keys and `delay_rate`/`overall_delay_rate`, `accepted_range` 0..1 on every rate
and 0..23 / 1..7 on hour / day-of-week, `unique` on `dim_airports.iata` and
carrier, `relationships` so route/airport origins (and route dests) exist in
`dim_airports`, and `unique_combination` composite-key tests on each aggregate's
grain. On the seeds: **seed 2/2, run 10/10, test 67/67 pass.**

## Layout

```
flight/
├── dbt_project.yml          project config + the use_seeds var + materializations
├── profiles.yml             self-contained duckdb profile (DUCKDB_PATH env)
├── packages.yml             empty (self-contained tests; dbt_utils optional)
├── .env.example
├── macros/
│   └── generate_schema_name.sql   keep marts in `main`
├── seeds/
│   ├── seed_airports.csv    12 airports
│   └── seed_flights.csv     96 sample flights
├── tests/generic/
│   ├── test_accepted_range.sql
│   └── test_unique_combination.sql
└── models/
    ├── staging/  _sources.yml, _staging.yml, stg_flights.sql, stg_airports.sql
    └── marts/    _marts.yml + the 8 mart models
```
