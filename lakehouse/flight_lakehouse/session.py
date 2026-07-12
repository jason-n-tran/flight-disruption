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
