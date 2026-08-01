"""Publish the trained model bundle + gold DuckDB to object storage.

The serving layer (``serving/flight_serving/artifacts_loader.py``) pulls, on
startup, the following keys from ``S3_BUCKET`` under ``S3_PREFIX``::

    {S3_PREFIX}/model.lgb
    {S3_PREFIX}/calibrator.pkl
    {S3_PREFIX}/feature_metadata.json
    {S3_PREFIX}/gold.duckdb

This script is the *producer* side of that contract: it uploads exactly those
four files. It is intentionally a small, dependency-light placeholder that:

* No-ops gracefully (exit 0) when the S3_* env is blank -- this is the normal
  state for the showcase / local runs, where artifacts simply stay on disk and
  a fresh clone uses the bundled sample. This keeps the Airflow DAG green.
* Uses boto3 (MinIO/B2/S3-compatible) when S3 is configured.

Env (all standard names, see CLAUDE.md):
    S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY,
    S3_PREFIX (default "artifacts/latest"), S3_REGION (default "us-east-1")
    ARTIFACTS_DIR (where model.lgb/calibrator.pkl/feature_metadata.json live)
    DUCKDB_PATH  (the gold.duckdb to publish)

Usage::

    python -m airflow.scripts.publish_artifacts             # uses env
    python publish_artifacts.py --artifacts ml/artifacts --duckdb data/lake/gold.duckdb
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# The bundle files the serving layer expects (must match artifacts_loader.py).
BUNDLE_FILES = ("model.lgb", "calibrator.pkl", "feature_metadata.json")
GOLD_FILE = "gold.duckdb"


def log(msg: str) -> None:
    print(f"[publish-artifacts] {msg}", flush=True)


def s3_enabled() -> bool:
    return bool(
        os.environ.get("S3_ENDPOINT")
        and os.environ.get("S3_BUCKET")
        and os.environ.get("S3_ACCESS_KEY_ID")
    )


def collect_files(artifacts_dir: Path, duckdb_path: Path) -> list[tuple[Path, str]]:
    """Return [(local_path, object_key_basename), ...] of files that exist."""
    pairs: list[tuple[Path, str]] = []
    for name in BUNDLE_FILES:
        p = artifacts_dir / name
        if p.exists():
            pairs.append((p, name))
        else:
            log(f"WARN missing bundle file (skipping): {p}")
    if duckdb_path.exists():
        pairs.append((duckdb_path, GOLD_FILE))
    else:
        log(f"WARN missing gold duckdb (skipping): {duckdb_path}")
    return pairs


def ensure_bucket_exists(client, bucket: str) -> None:
    """Create bucket if it doesn't exist (idempotent for S3-compatible stores)."""
    try:
        client.head_bucket(Bucket=bucket)
        log(f"bucket {bucket} exists")
    except Exception as e:
        # Bucket doesn't exist or other error; try to create it.
        log(f"bucket {bucket} not found, creating...")
        try:
            client.create_bucket(Bucket=bucket)
            log(f"created bucket {bucket}")
        except Exception as create_err:
            log(f"WARN could not create bucket (may already exist): {create_err}")


def upload(pairs: list[tuple[Path, str]]) -> None:
    import boto3  # imported lazily: only needed when actually uploading
    from botocore.exceptions import ClientError

    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ.get("S3_PREFIX", "artifacts/latest").rstrip("/")
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", ""),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    
    # Ensure bucket exists before uploading
    ensure_bucket_exists(client, bucket)
    
    for local, base in pairs:
        key = f"{prefix}/{base}"
        log(f"PUT s3://{bucket}/{key}  ({local.stat().st_size} bytes)")
        client.upload_file(str(local), bucket, key)
    log(f"uploaded {len(pairs)} object(s) to s3://{bucket}/{prefix}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Publish model + gold artifacts to object storage.")
    p.add_argument(
        "--artifacts",
        default=os.environ.get("ARTIFACTS_DIR", "ml/artifacts"),
        help="Directory holding model.lgb / calibrator.pkl / feature_metadata.json.",
    )
    p.add_argument(
        "--duckdb",
        default=os.environ.get("DUCKDB_PATH", "data/lake/gold.duckdb"),
        help="Path to the gold.duckdb to publish.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    args = build_parser().parse_args(argv)
    artifacts_dir = Path(args.artifacts)
    duckdb_path = Path(args.duckdb)

    pairs = collect_files(artifacts_dir, duckdb_path)
    log(f"candidate files: {[b for _, b in pairs]}")

    if not s3_enabled():
        log(
            "S3_* env not set -> no-op (artifacts remain on disk). "
            "This is expected for the showcase / local runs."
        )
        return 0

    if not pairs:
        log("ERROR: S3 configured but no artifacts found to upload.")
        return 1

    upload(pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
