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


def _bundle_present(directory: str) -> bool:
    d = Path(directory)
    return all((d / f).exists() for f in _BUNDLE_FILES)


def _pull_from_s3(settings: Settings) -> dict[str, str]:
    """Download the latest bundle + gold DuckDB from S3-compatible storage."""
    import boto3  # local import: only needed when S3 configured
    from botocore.config import Config as BotoConfig

    cache = Path(settings.artifact_cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint or None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    prefix = settings.s3_prefix.rstrip("/")
    wanted = list(_BUNDLE_FILES) + [_GOLD_FILE]
    pulled: list[str] = []
    for name in wanted:
        key = f"{prefix}/{name}"
        dest = cache / name
        try:
            client.download_file(settings.s3_bucket, key, str(dest))
            pulled.append(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not pull s3://%s/%s (%s)", settings.s3_bucket, key, exc)

    # Require the full model bundle; if any bundle file is missing, fall back.
    if not _bundle_present(str(cache)):
        log.warning(
            "S3 pull incomplete (got %s); falling back to local/sample", pulled
        )
        # Backfill any missing bundle file from the sample so the API still boots.
        _backfill_from_sample(settings, cache)
        if not _bundle_present(str(cache)):
            return _local_fallback(settings)

    gold_from_s3 = _GOLD_FILE in pulled
    duckdb_path = cache / _GOLD_FILE
    if not duckdb_path.exists():
        # No gold pulled — backfill from sample so queries still work.
        sample_gold = Path(settings.sample_dir) / _GOLD_FILE
        if sample_gold.exists():
            shutil.copyfile(sample_gold, duckdb_path)

    # Be honest about what actually came from S3 vs sample backfill, so the logs
    # don't claim an s3 pull when nothing was published yet (the common pre-
    # pipeline state — all keys 404).
    bundle_from_s3 = all(f in pulled for f in _BUNDLE_FILES)
    if bundle_from_s3 and gold_from_s3:
        source = "s3"
        log.info("Pulled all artifacts from s3://%s/%s", settings.s3_bucket, prefix)
    elif pulled:
        source = "s3+sample"
        log.warning(
            "Partial S3 pull (got %s); backfilled the rest from the bundled "
            "sample. Run the Working-PC pipeline to publish real artifacts.",
            pulled,
        )
    else:
        source = "sample"
        log.warning(
            "Nothing in s3://%s/%s yet (all keys 404) — serving the bundled "
            "SAMPLE model. This is expected until the Working-PC pipeline "
            "publishes real artifacts.", settings.s3_bucket, prefix,
        )
    return {
        "bundle_dir": str(cache),
        "duckdb_path": str(duckdb_path),
        "source": source,
    }


def _backfill_from_sample(settings: Settings, cache: Path) -> None:
    sample = Path(settings.sample_dir)
    for name in _BUNDLE_FILES:
        dest = cache / name
        src = sample / name
        if not dest.exists() and src.exists():
            shutil.copyfile(src, dest)
