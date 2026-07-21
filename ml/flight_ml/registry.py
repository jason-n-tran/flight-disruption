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


class _MlflowRun:
    def __init__(self, mlflow_mod):
        self._mlflow = mlflow_mod

    def _safe(self, fn):
        try:
            return fn()
        except Exception as exc:
            warnings.warn(f"mlflow call failed: {exc}")
            return None

    def log_params(self, params: dict):
        self._safe(lambda: self._mlflow.log_params(_stringify(params)))

    def log_metrics(self, metrics: dict):
        clean = {k: float(v) for k, v in metrics.items() if _is_number(v)}
        self._safe(lambda: self._mlflow.log_metrics(clean))

    def log_artifact(self, path: str):
        self._safe(lambda: self._mlflow.log_artifact(str(path)))

    def log_artifacts(self, path: str):
        self._safe(lambda: self._mlflow.log_artifacts(str(path)))

    def log_dict(self, obj: dict, artifact_file: str):
        self._safe(lambda: self._mlflow.log_dict(obj, artifact_file))

    def log_lightgbm(self, booster, model_name: str | None = None):
        """Log the LightGBM booster and (best-effort) register it."""
        import mlflow.lightgbm as ml_lgb

        info = self._safe(
            lambda: ml_lgb.log_model(booster, name="model")
        )
        name = model_name or os.environ.get("MLFLOW_MODEL_NAME", DEFAULT_MODEL_NAME)
        if info is not None:
            self._safe(
                lambda: self._mlflow.register_model(info.model_uri, name)
            )
        return info


def _is_number(v) -> bool:
    try:
        float(v)
        return v == v  # not NaN
    except (TypeError, ValueError):
        return False


def _stringify(params: dict) -> dict:
    return {k: (v if isinstance(v, (int, float, str, bool)) else str(v)) for k, v in params.items()}
