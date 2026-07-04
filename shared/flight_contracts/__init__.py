"""Flight Disruption Platform — shared contracts (single source of truth).

Every component (ingestion, lakehouse, dbt, ml, serving) imports from here so
schemas, feature lists, paths, and the leakage contract stay consistent.

Design decisions encoded here come from the grill-me design session; see the
project memory and 0.md for rationale.
"""

from .contract import (
    LABEL_COLUMN,
    DELAY_THRESHOLD_MIN,
    MODEL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    BANNED_LEAKY_COLUMNS,
    BTS_KEEP_COLUMNS,
    WEATHER_ARCHIVE_VARS,
    TRAIN_YEARS,
    TEST_YEARS,
    BRONZE_YEARS,
    US_BBOX,
    paths,
    valkey_key,
)

__all__ = [
    "LABEL_COLUMN",
    "DELAY_THRESHOLD_MIN",
    "MODEL_FEATURES",
    "CATEGORICAL_FEATURES",
    "NUMERIC_FEATURES",
    "BANNED_LEAKY_COLUMNS",
    "BTS_KEEP_COLUMNS",
    "WEATHER_ARCHIVE_VARS",
    "TRAIN_YEARS",
    "TEST_YEARS",
    "BRONZE_YEARS",
    "US_BBOX",
    "paths",
    "valkey_key",
]
