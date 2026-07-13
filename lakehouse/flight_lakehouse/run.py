"""CLI entrypoint: ``python -m flight_lakehouse.run --stage {silver|gold|all}``.

Reads LAKE_ROOT / DUCKDB_PATH (and the SPARK_* knobs) from env via
:func:`flight_lakehouse.config.load_config`.

Stages:
    silver : bronze -> silver (conform BTS/airports/weather).
    gold   : silver -> gold/fct_flight_features (leakage-safe features).
    duckdb : land gold parquet into the DuckDB file (no Spark).
    all    : silver -> gold -> duckdb.
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import load_config


def _log(msg: str) -> None:
    print(f"[flight-lakehouse] {msg}", flush=True)


def run_silver(cfg) -> None:
    from .session import build_spark
    from .silver import build_silver

    spark = build_spark(app_name="flight-lakehouse-silver", cfg=cfg)
    try:
        t0 = time.time()
        out = build_silver(spark, cfg)
        for name, df in out.items():
            _log(f"silver/{name}: {df.count():,} rows")
        _log(f"silver done in {time.time() - t0:.1f}s")
    finally:
        spark.stop()


def run_gold(cfg) -> None:
    from .gold_features import build_gold_features
    from .session import build_spark

    spark = build_spark(app_name="flight-lakehouse-gold", cfg=cfg)
    try:
        t0 = time.time()
        out = build_gold_features(spark, cfg)
        _log(f"gold/fct_flight_features: {out.count():,} rows")
        _log(f"gold done in {time.time() - t0:.1f}s")
    finally:
        spark.stop()


def run_duckdb(cfg) -> None:
    from .to_duckdb import parquet_to_duckdb

    path = parquet_to_duckdb(cfg)
    _log(f"duckdb written: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flight-lakehouse")
    parser.add_argument(
        "--stage",
        choices=["silver", "gold", "duckdb", "all"],
        default="all",
        help="Which stage(s) to run.",
    )
    parser.add_argument(
        "--no-duckdb",
        action="store_true",
        help="With --stage all, skip the DuckDB load step.",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    _log(f"LAKE_ROOT={cfg.lake_root} format={cfg.fmt} duckdb={cfg.duckdb_path}")

    if args.stage in ("silver", "all"):
        run_silver(cfg)
    if args.stage in ("gold", "all"):
        run_gold(cfg)
    if args.stage == "duckdb" or (args.stage == "all" and not args.no_duckdb):
        run_duckdb(cfg)

    _log("pipeline complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
