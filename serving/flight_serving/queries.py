"""Read-only DuckDB query helpers over the gold marts.

The gold DuckDB is opened **read-only** (it is a published, immutable artifact).
DuckDB connections are not thread-safe to share across threads, and FastAPI runs
sync route handlers in a threadpool, so we use a tiny connection pool keyed by
path and guarded by a lock — each query borrows a connection.

All table/column names come from ``flight_contracts.contract`` and were verified
against ``data/sample/gold.duckdb``.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

import duckdb

from flight_contracts.contract import (
    GOLD_AIRPORTS_DIM,
    GOLD_CARRIER_RELIABILITY,
    GOLD_ROUTE_RELIABILITY,
)

log = logging.getLogger("flight_serving.queries")

# Verified gold table names (some are not in the contract constants).
T_AIRPORTS = GOLD_AIRPORTS_DIM                       # dim_airports
T_ROUTE = GOLD_ROUTE_RELIABILITY                     # agg_route_reliability
T_ROUTE_CARRIER = "agg_route_carrier_reliability"
T_AIRPORT = "agg_airport_reliability"
T_AIRPORT_HOURLY = "agg_airport_hourly"
T_AIRPORT_WORST = "agg_airport_worst_routes"
T_CARRIER = GOLD_CARRIER_RELIABILITY                 # agg_carrier_reliability
T_FEATURES = "fct_flight_features"

# Friendly carrier names (the gold dim has codes only).
CARRIER_NAMES = {
    "AA": "American Airlines",
    "AS": "Alaska Airlines",
    "B6": "JetBlue Airways",
    "DL": "Delta Air Lines",
    "UA": "United Airlines",
    "WN": "Southwest Airlines",
    "NK": "Spirit Airlines",
    "F9": "Frontier Airlines",
    "G4": "Allegiant Air",
    "HA": "Hawaiian Airlines",
}


class GoldStore:
    """Thread-safe read-only access to the gold DuckDB."""

    def __init__(self, duckdb_path: str):
        self.duckdb_path = duckdb_path
        self._lock = threading.Lock()
        # A single read-only connection reused under a lock. Read-only + serialized
        # access is correct and simple; the demo's query volume is tiny.
        self._con = duckdb.connect(duckdb_path, read_only=True)

    def close(self) -> None:
        with self._lock:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001
                pass

    @contextmanager
    def _cursor(self):
        with self._lock:
            yield self._con

    def _has_table(self, name: str) -> bool:
        with self._cursor() as con:
            row = con.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = ? LIMIT 1",
                [name],
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # /api/meta/options
    # ------------------------------------------------------------------
    def airports(self) -> list[dict]:
        with self._cursor() as con:
            rows = con.execute(
                f"SELECT iata, name, lat, lon FROM {T_AIRPORTS} ORDER BY iata"
            ).fetchall()
        return [
            {"iata": r[0], "name": r[1], "lat": float(r[2]), "lon": float(r[3])}
            for r in rows
        ]

    def carriers(self) -> list[dict]:
        with self._cursor() as con:
            rows = con.execute(
                f"SELECT DISTINCT carrier FROM {T_CARRIER} ORDER BY carrier"
            ).fetchall()
        return [
            {"code": r[0], "name": CARRIER_NAMES.get(r[0], r[0])} for r in rows
        ]

    def example_presets(self, limit: int = 4) -> list[dict]:
        """A few interesting high-traffic routes as ready-made demo presets."""
        with self._cursor() as con:
            rows = con.execute(
                f"""
                SELECT r.origin, r.dest, rc.carrier
                FROM {T_ROUTE} r
                LEFT JOIN {T_ROUTE_CARRIER} rc
                  ON r.origin = rc.origin AND r.dest = rc.dest
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY r.origin, r.dest ORDER BY rc.flights DESC NULLS LAST
                ) = 1
                ORDER BY r.flights DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        presets = []
        for origin, dest, carrier in rows:
            presets.append(
                {
                    "origin": origin,
                    "dest": dest,
                    "carrier": carrier or "DL",
                    "day_of_week": 5,  # Friday — busy travel day
                    "dep_hour": 17,    # evening rush
                }
            )
        return presets

    # ------------------------------------------------------------------
    # /api/reliability/route
    # ------------------------------------------------------------------
    def route_reliability(self, origin: str, dest: str) -> dict | None:
        with self._cursor() as con:
            row = con.execute(
                f"""
                SELECT origin, dest, delay_rate, flights, avg_delay_min
                FROM {T_ROUTE}
                WHERE origin = ? AND dest = ?
                """,
                [origin, dest],
            ).fetchone()
            carriers = con.execute(
                f"""
                SELECT carrier, delay_rate
                FROM {T_ROUTE_CARRIER}
                WHERE origin = ? AND dest = ?
                ORDER BY flights DESC
                """,
                [origin, dest],
            ).fetchall()
        if row is None:
            return None
        return {
            "origin": row[0],
            "dest": row[1],
            "delay_rate": _f(row[2]),
            "flights": int(row[3]),
            "avg_delay_min": _f(row[4]),
            "by_carrier": [
                {"carrier": c[0], "delay_rate": _f(c[1])} for c in carriers
            ],
        }

    # ------------------------------------------------------------------
    # /api/airport/{iata} — historical portion
    # ------------------------------------------------------------------
    def airport_dim(self, iata: str) -> dict | None:
        with self._cursor() as con:
            row = con.execute(
                f"SELECT iata, name, lat, lon FROM {T_AIRPORTS} WHERE iata = ?",
                [iata],
            ).fetchone()
        if row is None:
            return None
        return {"iata": row[0], "name": row[1], "lat": float(row[2]), "lon": float(row[3])}

    def airport_historical(self, iata: str) -> dict:
        with self._cursor() as con:
            overall = con.execute(
                f"SELECT overall_delay_rate FROM {T_AIRPORT} WHERE origin = ?",
                [iata],
            ).fetchone()
            by_hour = con.execute(
                f"""
                SELECT hour, delay_rate FROM {T_AIRPORT_HOURLY}
                WHERE origin = ? ORDER BY hour
                """,
                [iata],
            ).fetchall()
            worst = con.execute(
                f"""
                SELECT dest, delay_rate FROM {T_AIRPORT_WORST}
                WHERE origin = ? ORDER BY delay_rate DESC
                """,
                [iata],
            ).fetchall()
        return {
            "overall_delay_rate": _f(overall[0]) if overall else None,
            "by_hour": [{"hour": int(h[0]), "delay_rate": _f(h[1])} for h in by_hour],
            "worst_routes": [
                {"dest": w[0], "delay_rate": _f(w[1])} for w in worst
            ],
        }

    # ------------------------------------------------------------------
    # Route distance lookup (for serve-time feature assembly)
    # ------------------------------------------------------------------
    def route_distance(self, origin: str, dest: str) -> tuple[float | None, float | None]:
        """Median (distance, crs_elapsed_time) for a route from the feature table."""
        if not self._has_table(T_FEATURES):
            return None, None
        with self._cursor() as con:
            row = con.execute(
                f"""
                SELECT median(distance), median(crs_elapsed_time)
                FROM {T_FEATURES}
                WHERE origin = ? AND dest = ?
                """,
                [origin, dest],
            ).fetchone()
        if not row or row[0] is None:
            return None, None
        return _f(row[0]), _f(row[1])

    def hist_rates(self, origin: str, dest: str, carrier: str) -> dict:
        """Serve-time historical reliability rates from the gold aggregates.

        These mirror the leakage-safe rolling features the model trained on
        (route / origin / carrier delay rates computed from history only).
        """
        out = {
            "route_hist_delay_rate": None,
            "origin_hist_delay_rate": None,
            "carrier_hist_delay_rate": None,
        }
        with self._cursor() as con:
            r = con.execute(
                f"SELECT delay_rate FROM {T_ROUTE} WHERE origin = ? AND dest = ?",
                [origin, dest],
            ).fetchone()
            o = con.execute(
                f"SELECT overall_delay_rate FROM {T_AIRPORT} WHERE origin = ?",
                [origin],
            ).fetchone()
            c = con.execute(
                f"SELECT delay_rate FROM {T_CARRIER} WHERE carrier = ?",
                [carrier],
            ).fetchone()
        if r:
            out["route_hist_delay_rate"] = _f(r[0])
        if o:
            out["origin_hist_delay_rate"] = _f(o[0])
        if c:
            out["carrier_hist_delay_rate"] = _f(c[0])
        return out


def _f(v) -> float | None:
    if v is None:
        return None
    return round(float(v), 6)
