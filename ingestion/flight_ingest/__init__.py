"""flight_ingest — ingestion layer for the Flight Disruption Platform.

Pulls the four raw sources into the bronze lake layer as parquet:

* BTS On-Time Performance (monthly ZIPs)        -> bronze/bts_ontime
* Open-Meteo archive (historical hourly weather) -> bronze/weather_hourly
* OpenFlights airports.dat (US airport dim)      -> bronze/airports
* OpenSky live state vectors (one-shot snapshot) -> sample/backfill only

All bronze paths come from ``flight_contracts.paths()``; column/feature/leakage
contracts come from ``flight_contracts`` and are never redefined here.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
