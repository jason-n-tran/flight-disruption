"""Local single-node SparkSession builder, tuned for a 16GB workstation.

Plain Parquet by default. If ``LAKE_FORMAT=delta`` and ``delta-spark`` is
installed, Delta extensions are configured via ``delta.configure_spark_with_delta_pip``.
The default path (parquet) never imports delta, so a bare ``pip install pyspark``
run works.
"""

from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession

from .config import LakeConfig, load_config


def _ensure_worker_python() -> None:
    """Pin driver + worker python to the current interpreter.

    On Windows / mixed envs PySpark otherwise tries ``python`` off PATH, which
    may not be the venv interpreter. Tests rely on this.
    """
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)


def _ensure_windows_hadoop() -> None:
    """Wire up winutils.exe + hadoop.dll on Windows so Spark's native local-FS
    IO works. No-op on non-Windows or when HADOOP_HOME is already set.

    Looks for a ``~\\hadoop\\bin\\winutils.exe`` install; if found, exports
    HADOOP_HOME and prepends its bin dir to PATH (Windows-format ``;`` separator
    so the child JVM can locate hadoop.dll on its library path).
    """
    if os.name != "nt" or os.environ.get("HADOOP_HOME"):
        return
    candidate = os.path.join(os.path.expanduser("~"), "hadoop")
    if os.path.exists(os.path.join(candidate, "bin", "winutils.exe")):
        os.environ["HADOOP_HOME"] = candidate
        os.environ["PATH"] = (
            os.path.join(candidate, "bin") + os.pathsep + os.environ.get("PATH", "")
        )


def build_spark(
    app_name: str = "flight-lakehouse",
    master: str = "local[*]",
    cfg: LakeConfig | None = None,
) -> SparkSession:
    """Build (or get) a tuned local SparkSession.

    Parameters
    ----------
    app_name : Spark application name.
    master   : Spark master URL. Default ``local[*]``; tests pass ``local[2]``.
    cfg      : optional LakeConfig (defaults to env-derived config).
    """
    _ensure_worker_python()
    _ensure_windows_hadoop()
    cfg = cfg or load_config()

    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        .config("spark.driver.memory", cfg.driver_memory)
        # Single-node: keep shuffle parallelism modest so we don't shred tiny
        # partitions into thousands of files.
        .config("spark.sql.shuffle.partitions", str(cfg.shuffle_partitions))
        # Arrow speeds up the pandas <-> Spark hops the dbt/duckdb handoff uses.
        # Toggleable: some Windows + Python 3.12 + pyarrow combos crash the
        # Python worker, so SPARK_ARROW_ENABLED=0 disables it.
        .config(
            "spark.sql.execution.arrow.pyspark.enabled",
            "true" if cfg.arrow_enabled else "false",
        )
        .config("spark.sql.execution.arrow.pyspark.fallback.enabled", "true")
        # Don't reuse Python workers — avoids a Windows worker-handshake crash.
        .config("spark.python.worker.reuse", "false")
        # Deterministic timestamp semantics for the flight_ts derivation.
        .config("spark.sql.session.timeZone", "UTC")
        # Quieter UI / no event log clutter on a laptop.
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.adaptive.enabled", "true")
    )

    if cfg.local_dir:
        builder = builder.config("spark.local.dir", cfg.local_dir)

    if cfg.is_delta:
        # Only import delta when explicitly enabled.
        from delta import configure_spark_with_delta_pip  # type: ignore

        builder = (
            builder.config(
                "spark.sql.extensions",
                "io.delta.sql.DeltaSparkSessionExtension",
            ).config(
                "spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog",
            )
        )
        spark = configure_spark_with_delta_pip(builder).getOrCreate()
    else:
        spark = builder.getOrCreate()

    spark.sparkContext.setLogLevel("WARN")
    return spark


def write_table(df, path: str, cfg: LakeConfig, partition_by=None, mode="overwrite"):
    """Write a DataFrame to ``path`` in the configured format.

    Centralises parquet-vs-delta so silver/gold modules stay format-agnostic.
    """
    writer = df.write.mode(mode)
    if partition_by:
        writer = writer.partitionBy(*partition_by)
    fmt = "delta" if cfg.is_delta else "parquet"
    writer.format(fmt).save(path)


def read_table(spark: SparkSession, path: str, cfg: LakeConfig):
    """Read a table written by :func:`write_table`."""
    fmt = "delta" if cfg.is_delta else "parquet"
    return spark.read.format(fmt).load(path)
