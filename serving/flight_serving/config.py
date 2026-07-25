"""Environment-driven configuration for the serving layer.

Every setting reads from an env var with a sensible local-dev default that points
at the bundled sample artifacts (``data/sample/``) so a fresh clone runs offline.

Resolution rules
----------------
* ``MODEL_PATH`` points at ``model.lgb``; the *bundle directory* is its parent
  (the dir holding ``model.lgb`` + ``calibrator.pkl`` + ``feature_metadata.json``).
  ``flight_ml.artifacts.load_bundle`` takes that directory.
* ``DUCKDB_PATH`` is the gold DuckDB file (opened read-only).
* ``SAMPLE_DIR`` is the bundled fallback bundle/positions dir (``data/sample``).
* ``S3_*`` (optional) enables pulling the latest artifacts on startup; when blank
  the bundled sample artifacts are used as-is (see ``artifacts_loader``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _repo_root() -> Path:
    # serving/flight_serving/config.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2]


def _default_sample_dir() -> str:
    env = os.environ.get("SAMPLE_DIR")
    if env:
        return env
    return str(_repo_root() / "data" / "sample")


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    # --- gold data ---
    duckdb_path: str = field(
        default_factory=lambda: os.environ.get(
            "DUCKDB_PATH", str(_repo_root() / "data" / "sample" / "gold.duckdb")
        )
    )
    # --- model bundle (MODEL_PATH points at model.lgb; bundle dir = its parent) ---
    model_path: str = field(
        default_factory=lambda: os.environ.get(
            "MODEL_PATH", str(_repo_root() / "data" / "sample" / "model.lgb")
        )
    )
    # --- bundled sample fallback (artifacts + positions.json) ---
    sample_dir: str = field(default_factory=_default_sample_dir)

    # --- live cache (Valkey / redis-protocol) ---
    valkey_host: str = field(
        default_factory=lambda: os.environ.get("VALKEY_HOST", "localhost")
    )
    valkey_port: int = field(
        default_factory=lambda: int(os.environ.get("VALKEY_PORT", "6379"))
    )
    valkey_enabled: bool = field(
        default_factory=lambda: os.environ.get("VALKEY_HOST", "").strip() != ""
        or os.environ.get("VALKEY_ENABLED", "").lower() in {"1", "true", "yes"}
    )
    # Positions older than this are still served but flagged; beyond cache TTL the
    # consumer overwrites, so this only governs the "live vs cached" label.
    live_fresh_seconds: int = field(
        default_factory=lambda: int(os.environ.get("LIVE_FRESH_SECONDS", "120"))
    )

    # --- CORS ---
    allowed_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.environ.get(
                "ALLOWED_ORIGINS",
                "http://localhost:5173,http://localhost:4173",
            )
        )
    )

    # --- data version surfaced in responses / /health ---
    data_version: str = field(
        default_factory=lambda: os.environ.get("DATA_VERSION", "sample")
    )

    # --- weather forecast (graceful-degrade if unreachable) ---
    weather_enabled: bool = field(
        default_factory=lambda: os.environ.get("WEATHER_ENABLED", "true").lower()
        not in {"0", "false", "no"}
    )
    weather_timeout_seconds: float = field(
        default_factory=lambda: float(os.environ.get("WEATHER_TIMEOUT_SECONDS", "4"))
    )

    # --- optional artifact pull from object storage (MinIO / B2 / S3) ---
    s3_endpoint: str = field(default_factory=lambda: os.environ.get("S3_ENDPOINT", ""))
    s3_bucket: str = field(default_factory=lambda: os.environ.get("S3_BUCKET", ""))
    s3_access_key_id: str = field(
        default_factory=lambda: os.environ.get("S3_ACCESS_KEY_ID", "")
    )
    s3_secret_access_key: str = field(
        default_factory=lambda: os.environ.get("S3_SECRET_ACCESS_KEY", "")
    )
    s3_prefix: str = field(
        default_factory=lambda: os.environ.get("S3_PREFIX", "artifacts/latest")
    )
    s3_region: str = field(
        default_factory=lambda: os.environ.get("S3_REGION", "us-east-1")
    )
    # Where pulled artifacts land (then becomes the active bundle/duckdb dir).
    artifact_cache_dir: str = field(
        default_factory=lambda: os.environ.get("ARTIFACT_CACHE_DIR", "/artifacts")
    )

    @property
    def bundle_dir(self) -> str:
        """Directory containing model.lgb + calibrator.pkl + feature_metadata.json."""
        return str(Path(self.model_path).resolve().parent)

    @property
    def s3_enabled(self) -> bool:
        return bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key_id)

    @property
    def positions_sample_path(self) -> str:
        return str(Path(self.sample_dir) / "positions.json")


def get_settings() -> Settings:
    """Build settings from the current environment (fresh each call)."""
    return Settings()
