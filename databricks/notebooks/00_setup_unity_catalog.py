# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — Unity Catalog setup: the governed lakehouse
# MAGIC
# MAGIC **Flight Disruption Intelligence Platform — Databricks + Unity Catalog showcase.**
# MAGIC
# MAGIC This notebook stands up the Unity Catalog (UC) namespace the rest of the
# MAGIC medallion writes into:
# MAGIC
# MAGIC ```
# MAGIC flight                 (catalog)
# MAGIC ├── bronze              raw, as-ingested (BTS / weather / airports)
# MAGIC ├── silver              cleaned + conformed (typed, deduped, derived cols)
# MAGIC └── gold                serving-ready (per-flight ML features + agg marts)
# MAGIC ```
# MAGIC
# MAGIC ## Why this exists (honest framing)
# MAGIC
# MAGIC The **source of truth for this platform is the local PySpark pipeline**
# MAGIC (`lakehouse/flight_lakehouse/`). This Databricks track re-implements the
# MAGIC *exact same medallion logic* — same conformance, same leakage-safe rolling
# MAGIC features, same gold feature table — inside a **governed lakehouse** so the
# MAGIC project can legitimately claim "Databricks + Unity Catalog" with real,
# MAGIC runnable notebooks and screenshot-able lineage / governance evidence.
# MAGIC
# MAGIC ## The governance story (the portfolio talking points)
# MAGIC
# MAGIC - **Three-layer separation as schemas.** Bronze / silver / gold are UC
# MAGIC   *schemas* under one *catalog*. Access can be granted per layer — analysts
# MAGIC   get `gold`, engineers get `silver`, only ingestion touches `bronze`.
# MAGIC - **Managed tables + default storage.** On Free Edition every table is a
# MAGIC   UC **managed Delta table** in the workspace default storage. No external
# MAGIC   locations or credentials to configure — UC governs the data lifecycle.
# MAGIC - **Automatic column- and table-level lineage.** Because every transform is
# MAGIC   a UC-governed Delta write, UC records the lineage graph end to end
# MAGIC   (BTS → silver flights → gold features). We surface it in notebook `05`.
# MAGIC - **Documentation as metadata.** Table/column `COMMENT`s live in UC, so the
# MAGIC   catalog itself is the data dictionary (not a stale wiki).
# MAGIC - **The leakage contract is enforced in code AND visible in governance.**
# MAGIC   Gold features assert no banned column leaked in (notebook `03`), and the
# MAGIC   column comments document each feature's "known before departure" status.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC `CATALOG` is a notebook widget so you can rename it if `flight` is taken in
# MAGIC your workspace. On **Databricks Free Edition** you have permission to create
# MAGIC catalogs in the managed metastore; if your workspace restricts `CREATE
# MAGIC CATALOG`, point `CATALOG` at an existing catalog you own and only the
# MAGIC schemas below will be created.

# COMMAND ----------

dbutils.widgets.text("catalog", "flight", "Unity Catalog name")
CATALOG = dbutils.widgets.get("catalog")
SCHEMAS = ["bronze", "silver", "gold"]
print(f"Target catalog: {CATALOG}")
print(f"Schemas:        {', '.join(SCHEMAS)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the catalog and the three medallion schemas
# MAGIC
# MAGIC We use `IF NOT EXISTS` everywhere so the notebook is idempotent — re-running
# MAGIC it is safe. Comments are attached at create time so the catalog is
# MAGIC self-documenting from the first run.

# COMMAND ----------

spark.sql(
    f"CREATE CATALOG IF NOT EXISTS {CATALOG} "
    "COMMENT 'Flight Disruption Intelligence Platform — governed medallion "
    "lakehouse (bronze/silver/gold). Mirrors the local PySpark pipeline.'"
)

spark.sql(f"USE CATALOG {CATALOG}")

spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.bronze "
    "COMMENT 'Raw, as-ingested data: BTS On-Time Performance, Open-Meteo "
    "hourly weather, OpenFlights airport dim. No business logic applied.'"
)
spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.silver "
    "COMMENT 'Cleaned + conformed: typed, deduped, leakage-safe derived "
    "columns (dep_hour, time_of_day_bucket, is_holiday_window). One row per "
    "scheduled flight.'"
)
spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.gold "
    "COMMENT 'Serving-ready: per-flight ML feature table (leakage-safe) plus "
    "aggregate reliability marts for the BI / API layer.'"
)

print("Catalog + schemas created (or already present).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify the namespace

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW SCHEMAS IN IDENTIFIER(:catalog)

# COMMAND ----------

# MAGIC %md
# MAGIC ## (Optional) Create a UC Volume for uploaded source files
# MAGIC
# MAGIC Databricks Free Edition may restrict outbound network access, so the
# MAGIC bronze notebook supports reading source files from a **UC Volume** you
# MAGIC upload by hand (BTS monthly ZIPs, `airports.dat`). A managed volume is the
# MAGIC governed place to land those files. Upload via *Catalog Explorer → the
# MAGIC volume → Upload*, or skip this if your workspace allows outbound HTTP.

# COMMAND ----------

spark.sql(
    f"CREATE VOLUME IF NOT EXISTS {CATALOG}.bronze.landing "
    "COMMENT 'Manual upload landing zone for source files (BTS ZIPs, "
    "airports.dat) when outbound network is restricted on Free Edition.'"
)
print(f"Volume ready: /Volumes/{CATALOG}/bronze/landing")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Example GRANTs (governance evidence)
# MAGIC
# MAGIC These illustrate the three-layer access model. They are **commented out**
# MAGIC because a single-user Free Edition workspace has no other principals to
# MAGIC grant to — running them as-is would fail on an unknown group. Uncomment and
# MAGIC substitute real groups/users to demonstrate, then screenshot
# MAGIC *Catalog Explorer → Permissions*. The full governance walk-through lives in
# MAGIC notebook `05_lineage_and_governance`.

# COMMAND ----------

# Analysts: read-only on the gold marts only.
# spark.sql(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `analysts`")
# spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.gold TO `analysts`")

# Data engineers: read silver + gold, no raw bronze.
# spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.silver TO `data_engineers`")
# spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.gold   TO `data_engineers`")

# Ingestion service principal: write bronze only.
# spark.sql(f"GRANT USE SCHEMA, CREATE TABLE, MODIFY ON SCHEMA {CATALOG}.bronze TO `ingestion_sp`")

print("GRANT examples are documented above (commented for single-user Free Edition).")

# COMMAND ----------

# MAGIC %md
# MAGIC **Next:** run `01_bronze_ingest` → `02_silver_conform` → `03_gold_features`
# MAGIC → `04_gold_marts` → `05_lineage_and_governance` in order.
