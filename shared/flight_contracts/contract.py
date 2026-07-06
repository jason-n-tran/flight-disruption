"""The leakage contract, feature lists, schemas, and shared paths.

All values here are empirically grounded (see project memory: BTS/weather/
OpenSky/OpenFlights findings). Changing anything here is an interface change
that affects multiple components — treat it like a schema migration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Prediction target
# ---------------------------------------------------------------------------
# BTS ships a prebuilt binary: departure delayed >= 15 min. Confirmed present.
LABEL_COLUMN = "dep_del15"
DELAY_THRESHOLD_MIN = 15

# ---------------------------------------------------------------------------
# Temporal split (NO random split — leakage via rolling features)
# ---------------------------------------------------------------------------
TRAIN_YEARS = [2022, 2023, 2024]
TEST_YEARS = [2025]
# Wider span ingested to bronze only, for dashboards / "we can scale" story.
BRONZE_YEARS = list(range(2015, 2026))

# ---------------------------------------------------------------------------
# Geographic scope — continental US (matches OpenSky bbox + weather backfill)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BBox:
    lamin: float
    lomin: float
    lamax: float
    lomax: float

    def as_params(self) -> dict[str, float]:
        return {
            "lamin": self.lamin,
            "lomin": self.lomin,
            "lamax": self.lamax,
            "lomax": self.lomax,
        }


US_BBOX = BBox(lamin=24.0, lomin=-125.0, lamax=50.0, lomax=-66.0)

# ---------------------------------------------------------------------------
# THE LEAKAGE CONTRACT
# ---------------------------------------------------------------------------
# Only features knowable BEFORE the flight departs may enter the model.
#
# Banned: every after-the-fact column (the answer), observed-at-arrival
# weather, live congestion. Confirmed present in BTS and excluded explicitly.
BANNED_LEAKY_COLUMNS = [
    "DepDelay",
    "DepDelayMinutes",
    "DepTime",
    "TaxiOut",
    "TaxiIn",
    "WheelsOff",
    "WheelsOn",
    "ArrTime",
    "ArrDelay",
    "ArrDelayMinutes",
    "ArrDel15",
    "ActualElapsedTime",
    "AirTime",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "DivAirportLandings",
]

# Raw BTS columns we keep from the 110-column file (pre-departure-safe + label
# + join keys + the leaky cols we keep ONLY in bronze for dashboards, never for
# the model). The lakehouse silver/gold build enforces the model contract.
BTS_KEEP_COLUMNS = [
    # identity / time
    "Year",
    "Month",
    "DayofMonth",
    "DayOfWeek",
    "FlightDate",
    "Reporting_Airline",
    "Flight_Number_Reporting_Airline",
    # route
    "Origin",
    "Dest",
    "Distance",
    # scheduled (pre-departure-safe)
    "CRSDepTime",
    "CRSArrTime",
    "CRSElapsedTime",
    # label
    "DepDel15",
    # kept for bronze/dashboards only (NOT model features)
    "DepDelayMinutes",
    "ArrDel15",
    "Cancelled",
    "Diverted",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
]

# ---------------------------------------------------------------------------
# Model features (the gold feature table column names — snake_case, conformed)
# ---------------------------------------------------------------------------
CATEGORICAL_FEATURES = [
    "origin",
    "dest",
    "carrier",
    "dep_hour",          # 0-23 from CRSDepTime
    "day_of_week",       # 1-7
    "month",             # 1-12
    "time_of_day_bucket",  # night/morning/afternoon/evening
]

NUMERIC_FEATURES = [
    "distance",
    "crs_elapsed_time",
    "is_holiday_window",          # within +/- 2 days of a US federal holiday
    # historical rolling reliability (computed ONLY from flights strictly
    # before the target flight's date — leakage-safe)
    "route_hist_delay_rate",
    "origin_hist_delay_rate",
    "carrier_hist_delay_rate",
    # weather forecast for scheduled dep window at ORIGIN (observed-as-proxy
    # at train time; real forecast at serve time). Visibility DROPPED (null on
    # Open-Meteo archive).
    "origin_temp_2m",
    "origin_precip",
    "origin_wind_speed",
    "origin_wind_gusts",
    "origin_snowfall",
    # weather at DEST
    "dest_temp_2m",
    "dest_precip",
    "dest_wind_speed",
    "dest_wind_gusts",
    "dest_snowfall",
]

MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# ---------------------------------------------------------------------------
# Weather (Open-Meteo archive vars — visibility EXCLUDED: null on archive)
# ---------------------------------------------------------------------------
WEATHER_ARCHIVE_VARS = [
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "snowfall",
]

# ---------------------------------------------------------------------------
# Shared filesystem paths (lake root is env-overridable)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Paths:
    lake_root: str

    @property
    def bronze(self) -> str:
        return os.path.join(self.lake_root, "bronze")

    @property
    def silver(self) -> str:
        return os.path.join(self.lake_root, "silver")

    @property
    def gold(self) -> str:
        return os.path.join(self.lake_root, "gold")

    def bronze_table(self, name: str) -> str:
        return os.path.join(self.bronze, name)

    def silver_table(self, name: str) -> str:
        return os.path.join(self.silver, name)

    def gold_table(self, name: str) -> str:
        return os.path.join(self.gold, name)


def paths(lake_root: str | None = None) -> Paths:
    return Paths(lake_root or os.environ.get("LAKE_ROOT", os.path.abspath("./data/lake")))


# ---------------------------------------------------------------------------
# Valkey keyspace — shared instance, `flight:` prefix (see serving stores memory)
# ---------------------------------------------------------------------------
VALKEY_PREFIX = "flight:"


def valkey_key(*parts: str) -> str:
    return VALKEY_PREFIX + ":".join(parts)


# Canonical gold table names (dbt + serving must agree on these)
GOLD_FEATURES_TABLE = "fct_flight_features"          # per-flight ML feature rows
GOLD_ROUTE_RELIABILITY = "agg_route_reliability"     # delay % by route
GOLD_AIRPORT_RELIABILITY = "agg_airport_reliability"  # delay % by airport
GOLD_CARRIER_RELIABILITY = "agg_carrier_reliability"  # delay % by carrier
GOLD_HOURLY_PATTERNS = "agg_hourly_patterns"          # delay % by hour/dow
GOLD_AIRPORTS_DIM = "dim_airports"                    # IATA -> name/lat/lon
