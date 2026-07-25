"""Artifact handoff: get the model bundle + gold DuckDB onto local disk.

This implements the **artifact-handoff mechanism** described in the project
memory: the batch/ML track publishes a versioned bundle (``model.lgb``,
``calibrator.pkl``, ``feature_metadata.json``) plus the gold ``gold.duckdb`` to
object storage (MinIO / Backblaze B2 / any S3-compatible store). On startup the
serving API pulls the **latest** bundle into a local cache dir and serves from
it. This keeps the API stateless and lets the (intermittent) Working-PC pipeline
push fresh artifacts without redeploying the API.

It is fully OPTIONAL and guarded:

* If ``S3_*`` env vars are set -> pull ``S3_PREFIX/{model.lgb,calibrator.pkl,
  feature_metadata.json,gold.duckdb}`` into ``ARTIFACT_CACHE_DIR`` and point the
  active paths there.
* Otherwise -> use the bundled sample artifacts (``SAMPLE_DIR`` / the paths from
  config) as-is. No network, works offline, fresh-clone friendly.

Any pull failure degrades gracefully back to whatever is already on disk so the
demo never fails to boot.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .config import Settings

log = logging.getLogger("flight_serving.artifacts")

# Files that make up a published artifact set.
_BUNDLE_FILES = ("model.lgb", "calibrator.pkl", "feature_metadata.json")
_GOLD_FILE = "gold.duckdb"


def ensure_local_artifacts(settings: Settings) -> dict[str, str]:
    """Resolve the active bundle dir + duckdb path, pulling from S3 if configured.

    Returns a dict ``{"bundle_dir": ..., "duckdb_path": ..., "source": ...}``.
    Never raises: on any failure it falls back to the configured local paths.
    """
    if settings.s3_enabled:
        try:
            return _pull_from_s3(settings)
        except Exception as exc:  # noqa: BLE001 — degrade to local on any failure
            log.warning(
                "S3 artifact pull failed (%s); falling back to local/sample artifacts",
                exc,
            )

    return _local_fallback(settings)


def _local_fallback(settings: Settings) -> dict[str, str]:
    bundle_dir = settings.bundle_dir
    duckdb_path = settings.duckdb_path

    # If the configured bundle/duckdb are missing but the sample dir has them,
    # transparently fall back to the bundled sample (self-contained dev/CI).
    if not _bundle_present(bundle_dir):
        sample = settings.sample_dir
        if _bundle_present(sample):
            log.info("Using bundled sample artifacts at %s", sample)
            bundle_dir = sample
    if not Path(duckdb_path).exists():
        sample_gold = str(Path(settings.sample_dir) / _GOLD_FILE)
        if Path(sample_gold).exists():
            duckdb_path = sample_gold

    return {
        "bundle_dir": bundle_dir,
        "duckdb_path": duckdb_path,
        "source": "sample" if bundle_dir == settings.sample_dir else "local",
    }
