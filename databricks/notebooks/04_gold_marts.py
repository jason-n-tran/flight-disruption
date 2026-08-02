# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Gold: aggregate reliability marts (`flight.gold.agg_*`, `dim_airports`)
# MAGIC
# MAGIC Mirrors the dbt-duckdb marts (`dbt/flight/models/marts/`). These feed the
# MAGIC BI / API / dashboard layer (route, airport, carrier, hourly reliability).
# MAGIC Built from `silver.flights` with the **same exclusion as dbt
# MAGIC `stg_flights`: cancelled rows are dropped** so a cancellation is never
# MAGIC silently counted as "not delayed".
# MAGIC
# MAGIC | Gold mart                          | Grain                  | dbt model |
# MAGIC |------------------------------------|------------------------|-----------|
# MAGIC | `agg_route_reliability`            | origin+dest            | ✓ |
# MAGIC | `agg_route_carrier_reliability`    | origin+dest+carrier    | ✓ |
# MAGIC | `agg_airport_reliability`          | origin                 | ✓ |
# MAGIC | `agg_airport_hourly`               | origin+hour            | ✓ |
# MAGIC | `agg_airport_worst_routes`         | origin+dest (ranked)   | ✓ |
# MAGIC | `agg_carrier_reliability`          | carrier                | ✓ |
# MAGIC | `agg_hourly_patterns`              | dep_hour+day_of_week   | ✓ |
# MAGIC | `dim_airports`                     | iata                   | ✓ |
# MAGIC
# MAGIC Mart names match the contract (`GOLD_ROUTE_RELIABILITY`, etc.).

# COMMAND ----------

dbutils.widgets.text("catalog", "flight", "Unity Catalog name")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")
print(f"catalog={CATALOG}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## `stg_flights` equivalent — exclude cancelled operated flights
# MAGIC
# MAGIC The reliability marts describe operated flights. We build a temp view that
# MAGIC excludes cancelled rows (mirroring the dbt `stg_flights` `where` clause),
# MAGIC then express each mart as Spark SQL against it.

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TEMP VIEW stg_flights AS
    SELECT *
    FROM {CATALOG}.silver.flights
    WHERE coalesce(cast(cancelled AS int), 0) = 0
    """
)
print("temp view stg_flights ready (cancelled excluded).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_route_reliability — one row per origin+dest

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_route_reliability AS
    SELECT
        origin,
        dest,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate,
        avg(dep_delay_minutes)         AS avg_delay_min
    FROM stg_flights
    GROUP BY origin, dest
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_route_carrier_reliability — one row per origin+dest+carrier

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_route_carrier_reliability AS
    SELECT
        origin,
        dest,
        carrier,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate
    FROM stg_flights
    GROUP BY origin, dest, carrier
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_airport_reliability — one row per origin

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_airport_reliability AS
    SELECT
        origin,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS overall_delay_rate
    FROM stg_flights
    GROUP BY origin
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_airport_hourly — one row per origin+hour

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_airport_hourly AS
    SELECT
        origin,
        dep_hour                       AS hour,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate
    FROM stg_flights
    GROUP BY origin, dep_hour
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_airport_worst_routes — routes ranked worst-first per origin

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_airport_worst_routes AS
    SELECT
        origin,
        dest,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate,
        row_number() OVER (
            PARTITION BY origin
            ORDER BY avg(cast(dep_del15 AS double)) DESC, count(*) DESC
        )                              AS rnk
    FROM stg_flights
    GROUP BY origin, dest
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_carrier_reliability — one row per carrier

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_carrier_reliability AS
    SELECT
        carrier,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate
    FROM stg_flights
    GROUP BY carrier
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## agg_hourly_patterns — one row per dep_hour+day_of_week

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.agg_hourly_patterns AS
    SELECT
        dep_hour,
        day_of_week,
        count(*)                       AS flights,
        avg(cast(dep_del15 AS double)) AS delay_rate
    FROM stg_flights
    GROUP BY dep_hour, day_of_week
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## dim_airports — one row per IATA (served at /api/meta/options)

# COMMAND ----------

spark.sql(
    f"""
    CREATE OR REPLACE TABLE {CATALOG}.gold.dim_airports AS
    SELECT iata, name, city, lat, lon
    FROM {CATALOG}.silver.airports
    """
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Table comments

# COMMAND ----------

_MART_DOC = {
    "agg_route_reliability": "Per-route reliability (origin+dest): flights, delay_rate, avg_delay_min.",
    "agg_route_carrier_reliability": "Per-route-per-carrier reliability (by_carrier breakdown for the route API).",
    "agg_airport_reliability": "Per-origin overall delay rate.",
    "agg_airport_hourly": "Per-origin per-hour delay rate (by_hour chart).",
    "agg_airport_worst_routes": "Per-origin routes ranked worst-first (rnk lets serving take top N).",
    "agg_carrier_reliability": "Per-carrier delay rate.",
    "agg_hourly_patterns": "Delay rate by dep_hour x day_of_week (temporal patterns chart).",
    "dim_airports": "Airport dimension: iata -> name/city/lat/lon.",
}
for tbl, doc in _MART_DOC.items():
    spark.sql(f"COMMENT ON TABLE {CATALOG}.gold.{tbl} IS '{doc}'")
print("gold mart comments set.")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT origin, dest, flights, round(delay_rate, 3) AS delay_rate
# MAGIC FROM IDENTIFIER(:catalog || '.gold.agg_route_reliability')
# MAGIC WHERE flights >= 50
# MAGIC ORDER BY delay_rate DESC
# MAGIC LIMIT 10
