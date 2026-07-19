"""Historical base-rate baseline — the bar the model must beat.

A delay model is only worth deploying if it beats the dumb-but-honest baseline:
"predict each route's historical delay rate". We compute the per-route
(origin -> dest) delay rate from the TRAIN set only, then score test rows by
looking up their route. Unseen routes fall back to the global TRAIN mean (the
prior). This is exactly the ``baseline_probability`` surfaced in the API.

Computing the baseline from TRAIN only (never test) keeps the comparison fair and
leakage-free, mirroring the model's temporal discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import LABEL_COLUMN


@dataclass
class BaseRateBaseline:
    """Per-route historical delay-rate predictor (fit on TRAIN only)."""

    global_prior: float = 0.0
    route_rates: dict[tuple[str, str], float] = field(default_factory=dict)
    min_route_count: int = 30  # routes with fewer train flights fall back to prior

    def fit(self, train: pd.DataFrame) -> "BaseRateBaseline":
        self.global_prior = float(train[LABEL_COLUMN].mean())
        # observed=True: origin/dest are categorical, so the default would form
        # the full origin x dest Cartesian product (mostly-empty groups) — slow
        # and memory-heavy. Only group combinations that actually occur.
        grp = train.groupby(["origin", "dest"], observed=True)[LABEL_COLUMN].agg(
            ["mean", "count"]
        )
        self.route_rates = {
            (o, d): float(row["mean"])
            for (o, d), row in grp.iterrows()
            if row["count"] >= self.min_route_count
        }
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        keys = list(zip(df["origin"].astype(str), df["dest"].astype(str)))
        return np.array(
            [self.route_rates.get(k, self.global_prior) for k in keys],
            dtype="float64",
        )

    def predict_one(self, origin: str, dest: str) -> float:
        return self.route_rates.get((str(origin), str(dest)), self.global_prior)

    # ---- serialization helpers (consumed by feature_metadata.json) ----
    def to_dict(self) -> dict:
        return {
            "global_prior": self.global_prior,
            "min_route_count": self.min_route_count,
            # JSON can't key on tuples -> use "ORIGIN|DEST"
            "route_rates": {f"{o}|{d}": r for (o, d), r in self.route_rates.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BaseRateBaseline":
        obj = cls(
            global_prior=float(payload["global_prior"]),
            min_route_count=int(payload.get("min_route_count", 30)),
        )
        obj.route_rates = {
            tuple(k.split("|", 1)): float(v)  # type: ignore[misc]
            for k, v in payload.get("route_rates", {}).items()
        }
        return obj
