"""Stage 3 — land gold parquet into a DuckDB file for dbt + the serving layer.

Keep it simple: register each gold parquet dir as a DuckDB table. dbt builds the
agg marts on top; the serving layer reads ``fct_flight_features`` and the dims.

This uses the ``duckdb`` python package directly (no Spark needed), so it can run
standalone after the gold stage. DuckDB reads Hive-partitioned parquet natively.
"""

from __future__ import annotations

import glob
import os

import duckdb

from flight_contracts.contract import GOLD_AIRPORTS_DIM, GOLD_FEATURES_TABLE

from .config import SILVER_AIRPORTS, LakeConfig, load_config


def _has_parquet(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    return bool(glob.glob(os.path.join(path, "**", "*.parquet"), recursive=True))


def parquet_to_duckdb(cfg: LakeConfig | None = None) -> str:
    """Register the gold (and a dim) parquet dirs as DuckDB tables.

    Returns the DuckDB file path. Creates:
      - ``fct_flight_features`` from gold/fct_flight_features
      - ``dim_airports`` from silver/airports (the airports dim feeding gold)

    dbt then materialises the agg_* marts from these. Idempotent: tables are
    replaced on each run.
    """
    cfg = cfg or load_config()

    os.makedirs(os.path.dirname(os.path.abspath(cfg.duckdb_path)) or ".", exist_ok=True)
    con = duckdb.connect(cfg.duckdb_path)
    try:
        con.execute("INSTALL parquet; LOAD parquet;")
    except Exception:
        # Parquet is built-in in modern duckdb; ignore if INSTALL is a no-op.
        pass

    mappings: list[tuple[str, str]] = []

    feats_dir = cfg.paths.gold_table(GOLD_FEATURES_TABLE)
    if _has_parquet(feats_dir):
        mappings.append((GOLD_FEATURES_TABLE, feats_dir))

    # Airports dim: gold dim if present, else the silver airports table.
    gold_airports = cfg.paths.gold_table(GOLD_AIRPORTS_DIM)
    silver_airports = cfg.paths.silver_table(SILVER_AIRPORTS)
    if _has_parquet(gold_airports):
        mappings.append((GOLD_AIRPORTS_DIM, gold_airports))
    elif _has_parquet(silver_airports):
        mappings.append((GOLD_AIRPORTS_DIM, silver_airports))

    if not mappings:
        raise FileNotFoundError(
            f"No gold/silver parquet found under {cfg.lake_root!r}; "
            "run the silver+gold stages first."
        )

    for table, path in mappings:
        # hive_partitioning=1 reconstructs the `year=` partition column.
        glob_expr = os.path.join(path, "**", "*.parquet").replace("\\", "/")
        con.execute(f'DROP TABLE IF EXISTS "{table}"')
        con.execute(
            f'CREATE TABLE "{table}" AS '
            f"SELECT * FROM read_parquet('{glob_expr}', hive_partitioning=1)"
        )

    con.close()
    return cfg.duckdb_path
