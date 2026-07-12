"""flight_lakehouse — PySpark medallion (bronze -> silver -> gold) for the
Flight Disruption Intelligence Platform.

Public surface:
    - session.build_spark()  : local single-node SparkSession tuned for 16GB.
    - silver.build_silver()  : conform bronze BTS / airports / weather -> silver.
    - gold_features.build_gold_features() : leakage-safe per-flight ML features.
    - to_duckdb.parquet_to_duckdb() : land gold parquet into a DuckDB file.
"""

from __future__ import annotations

__all__ = [
    "build_spark",
    "build_silver",
    "build_gold_features",
    "parquet_to_duckdb",
]

__version__ = "0.1.0"


def __getattr__(name: str):  # lazy import so `import flight_lakehouse` is cheap
    if name == "build_spark":
        from .session import build_spark

        return build_spark
    if name == "build_silver":
        from .silver import build_silver

        return build_silver
    if name == "build_gold_features":
        from .gold_features import build_gold_features

        return build_gold_features
    if name == "parquet_to_duckdb":
        from .to_duckdb import parquet_to_duckdb

        return parquet_to_duckdb
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
