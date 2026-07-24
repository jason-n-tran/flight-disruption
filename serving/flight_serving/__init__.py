"""FastAPI serving layer for the Flight Disruption Intelligence Platform.

Loads the native LightGBM model + live SHAP (via ``flight_ml``), reads gold marts
from DuckDB (read-only), and the live aircraft cache from Valkey — with graceful
fallback to bundled sample data so the demo never shows a broken/empty state.
"""

__version__ = "0.1.0"
