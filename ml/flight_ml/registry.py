"""MLflow tracking + model registry.

MLflow is a core deliverable here (the MLOps story), but it must never crash a
training run. So: if ``MLFLOW_TRACKING_URI`` is unset we default to a LOCAL FILE
STORE (``./mlruns``) — no server required — and every tracking call is guarded so
a misconfigured/unreachable backend degrades to a logged warning instead of an
exception. Registration is attempted and skipped gracefully if the backend
doesn't support a registry (the file store does support runs + artifacts).
"""

from __future__ import annotations

import os
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_EXPERIMENT = "flight_delay"
DEFAULT_MODEL_NAME = "flight_delay_lgbm"


def _resolve_tracking_uri() -> str:
    # MLflow 3.x raises on the file store unless this opt-out is set. We default
    # to the lightweight file store (no server / DB required) for the portfolio
    # demo, so enable the opt-out unless the user explicitly configured a backend.
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if uri:
        return uri
    # default to a local file store under the ml/ component root
    root = Path(__file__).resolve().parent.parent / "mlruns"
    root.mkdir(parents=True, exist_ok=True)
    return root.as_uri()


@contextmanager
def tracking_run(
    run_name: str = "pipeline",
    experiment: str | None = None,
    tags: dict[str, Any] | None = None,
):
    """Context manager yielding an MLflow-ish handle that is always safe to call.

    Yields a small shim with ``log_params/log_metrics/log_artifact/log_dict`` and
    ``log_lightgbm`` that no-op (with a warning) on any failure. Always yields —
    even if mlflow itself can't start — so the pipeline body runs unchanged.
    """
    # MLflow uses GitPython to tag runs with the source commit; in the
    # lake-builder container git isn't installed, which spews multi-line
    # warnings per run. We don't need git provenance here (the artifact bundle
    # is versioned in object storage), so silence it. Must be set before the
    # mlflow import. Harmless where git IS present.
    os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")
    try:
        import mlflow  # noqa: F401
    except Exception as exc:  # pragma: no cover - mlflow is a declared dep
        warnings.warn(f"mlflow unavailable ({exc}); tracking disabled.")
        yield _NoopRun()
        return

    try:
        mlflow.set_tracking_uri(_resolve_tracking_uri())
        mlflow.set_experiment(experiment or os.environ.get("MLFLOW_EXPERIMENT", DEFAULT_EXPERIMENT))
        active = mlflow.start_run(run_name=run_name)
    except Exception as exc:
        warnings.warn(f"mlflow.start_run failed ({exc}); tracking disabled.")
        yield _NoopRun()
        return

    run = _MlflowRun(mlflow)
    try:
        if tags:
            run._safe(lambda: mlflow.set_tags(tags))
        yield run
    finally:
        try:
            mlflow.end_run()
        except Exception:
            pass


class _NoopRun:
    def log_params(self, *_a, **_k): ...
    def log_metrics(self, *_a, **_k): ...
    def log_artifact(self, *_a, **_k): ...
    def log_artifacts(self, *_a, **_k): ...
    def log_dict(self, *_a, **_k): ...
    def log_lightgbm(self, *_a, **_k): return None
    def register(self, *_a, **_k): return None
