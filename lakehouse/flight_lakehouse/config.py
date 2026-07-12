"""Lakehouse configuration — all knobs read from env with sane local defaults.

Standard env names (shared across the platform; see CLAUDE.md):
    LAKE_ROOT     : root of the medallion (bronze/silver/gold live under it).
    DUCKDB_PATH   : path to the DuckDB file the dbt project + serving read.
    LAKE_FORMAT   : "parquet" (default) or "delta". Delta needs the `delta`
                    extra installed; the default local run must work on pyspark
                    alone, so it stays OFF unless explicitly enabled.
    SPARK_DRIVER_MEMORY    : driver heap (default 6g — comfortable on 16GB).
    SPARK_SHUFFLE_PARTITIONS : shuffle parallelism (default 64 for single-node).
    SPARK_LOCAL_DIR        : spill dir (optional).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from flight_contracts.contract import paths as contract_paths

# Bronze table dir names produced by the ingestion component (fixed schemas).
BRONZE_BTS = "bts_ontime"
BRONZE_WEATHER = "weather_hourly"
BRONZE_AIRPORTS = "airports"

# Silver table dir names.
SILVER_FLIGHTS = "flights"
SILVER_AIRPORTS = "airports"
SILVER_WEATHER = "weather"


@dataclass(frozen=True)
class LakeConfig:
    lake_root: str
    duckdb_path: str
    fmt: str  # "parquet" | "delta"
    driver_memory: str
    shuffle_partitions: int
    local_dir: str | None
    arrow_enabled: bool

    @property
    def paths(self):
        return contract_paths(self.lake_root)

    @property
    def is_delta(self) -> bool:
        return self.fmt == "delta"


def load_config() -> LakeConfig:
    lake_root = os.environ.get("LAKE_ROOT", os.path.abspath("./data/lake"))
    duckdb_path = os.environ.get(
        "DUCKDB_PATH", os.path.join(lake_root, "gold.duckdb")
    )
    fmt = os.environ.get("LAKE_FORMAT", "parquet").lower()
    if fmt not in ("parquet", "delta"):
        raise ValueError(f"LAKE_FORMAT must be parquet|delta, got {fmt!r}")
    return LakeConfig(
        lake_root=lake_root,
        duckdb_path=duckdb_path,
        fmt=fmt,
        driver_memory=os.environ.get("SPARK_DRIVER_MEMORY", "6g"),
        shuffle_partitions=int(os.environ.get("SPARK_SHUFFLE_PARTITIONS", "64")),
        local_dir=os.environ.get("SPARK_LOCAL_DIR") or None,
        # Arrow accelerates pandas<->Spark hops. Enabled by default, but it can
        # crash the Python worker on some Windows + Python 3.12 + pyarrow combos;
        # set SPARK_ARROW_ENABLED=0 to fall back to the pure-Python path.
        arrow_enabled=os.environ.get("SPARK_ARROW_ENABLED", "1").lower()
        not in ("0", "false", "no"),
    )
