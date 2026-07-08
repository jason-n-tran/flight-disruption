"""Open-Meteo historical (archive) weather ingestion.

For each airport (lat/lon from the OpenFlights dim) one archive call returns the
full multi-year hourly series. We request exactly ``WEATHER_ARCHIVE_VARS`` —
``visibility`` is NULL on the archive endpoint and is intentionally never asked
for. Output: ``bronze/weather_hourly`` parquet (iata, time, + archive vars).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from flight_contracts import BRONZE_YEARS, WEATHER_ARCHIVE_VARS

from ._http import get_with_retry, make_client
from .config import OPEN_METEO_ARCHIVE_URL, Settings

log = logging.getLogger("flight_ingest.weather")

BRONZE_TABLE = "weather_hourly"
# Cooldown marker written when the daily quota is exhausted. On the next run we
# do ONE cheap probe instead of spamming; if it still 429s we skip cleanly.
_COOLDOWN_FILE = "_weather_quota_cooldown.json"
BTS_BRONZE_TABLE = "bts_ontime"

# Hard guard against the visibility-on-archive trap, regardless of caller input.
_FORBIDDEN_ARCHIVE_VARS = {"visibility"}


def _date_range(years: list[int]) -> tuple[str, str]:
    start = f"{min(years)}-01-01"
    end = f"{max(years)}-12-31"
    return start, end


def build_archive_params(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    """Construct Open-Meteo archive query params for one location.

    Asserts visibility is never requested (training-leakage / null-data guard).
    """
    hourly_vars = list(WEATHER_ARCHIVE_VARS)
    assert not (_FORBIDDEN_ARCHIVE_VARS & set(hourly_vars)), (
        "visibility must never be requested from the archive endpoint"
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(hourly_vars),
        "timezone": "UTC",
    }


def parse_archive_response(iata: str, payload: dict) -> pd.DataFrame:
    """Turn an Open-Meteo archive JSON payload into a tidy per-hour frame."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    data: dict[str, object] = {"iata": iata, "time": times}
    for var in WEATHER_ARCHIVE_VARS:
        data[var] = hourly.get(var, [None] * len(times))
    df = pd.DataFrame(data, columns=["iata", "time", *WEATHER_ARCHIVE_VARS])
    if not df.empty:
        # Microsecond precision (NOT the pandas default ns): Spark 3.5 rejects
        # Parquet TIMESTAMP(NANOS) with "Illegal Parquet type INT64
        # (TIMESTAMP(NANOS,true))". us is the widest precision Spark reads.
        df["time"] = (
            pd.to_datetime(df["time"], utc=True).dt.tz_convert("UTC").astype("datetime64[us, UTC]")
        )
    return df


def fetch_airport(
    settings: Settings,
    client,
    iata: str,
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch the full archive series for a single airport."""
    params = build_archive_params(lat, lon, start_date, end_date)
    resp = get_with_retry(
        client,
        OPEN_METEO_ARCHIVE_URL,
        max_retries=settings.max_retries,
        pause=settings.request_pause_sec,
        max_backoff=settings.max_backoff_sec,
        params=params,
    )
    return parse_archive_response(iata, resp.json())


def repair_timestamp_precision(settings: Settings) -> int:
    """Rewrite already-written weather parquet whose `time` column is nanosecond
    precision down to microseconds (Spark 3.5 rejects TIMESTAMP(NANOS)).

    Idempotent: files already at us/ms precision are left untouched. Returns the
    count of files repaired. Lets us fix existing bronze WITHOUT re-fetching
    (which would spend Open-Meteo quota again).
    """
    base = Path(settings.paths.bronze_table(BRONZE_TABLE))
    files = sorted(base.rglob("*.parquet"))
    repaired = 0
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception as exc:  # noqa: BLE001
            log.warning("Skip repair (unreadable) %s: %s", f, exc)
            continue
        if "time" not in df.columns:
            continue
        unit = getattr(df["time"].dtype, "unit", None)
        if unit != "ns":
            continue  # already us/ms or not a datetime — nothing to do
        df["time"] = df["time"].astype("datetime64[us, UTC]")
        df.to_parquet(f, index=False)
        repaired += 1
        log.info("Repaired ns->us timestamps: %s", f)
    log.info("Timestamp repair complete: %d/%d file(s) rewritten.", repaired, len(files))
    return repaired


def _partition_file(settings: Settings, iata: str) -> Path:
    base = Path(settings.paths.bronze_table(BRONZE_TABLE))
    return base / f"iata={iata}" / "data.parquet"


def airports_in_bts(
    settings: Settings,
    airports: pd.DataFrame,
    *,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Restrict ``airports`` to those that actually appear in the bronze BTS data.

    Open-Meteo weights each archive call by (variables x days), so a 4-year x
    5-var pull is *heavy*. Fetching all ~1,251 US airports (incl. tiny Alaska
    strips with zero scheduled flights) blows the free quota. We only need
    weather for airports that appear as a BTS origin/dest. Optionally keep just
    the busiest ``top_n`` by flight volume — these cover the vast majority of
    flights and keep us well under the rate limit.

    Falls back to the full airport list if bronze BTS isn't present yet.
    """
    bts_dir = Path(settings.paths.bronze_table(BTS_BRONZE_TABLE))
    files = sorted(bts_dir.rglob("*.parquet"))
    if not files:
        log.warning(
            "No bronze BTS found at %s; weather will cover ALL %d airports "
            "(may hit Open-Meteo rate limits). Ingest BTS first to scope this.",
            bts_dir, len(airports),
        )
        return airports

    counts: dict[str, int] = {}
    for f in files:
        df = pd.read_parquet(f, columns=["origin", "dest"])
        for col in ("origin", "dest"):
            vc = df[col].value_counts()
            for code, n in vc.items():
                counts[code] = counts.get(code, 0) + int(n)

    used = set(counts)
    scoped = airports[airports["iata"].isin(used)].copy()
    scoped["_flights"] = scoped["iata"].map(counts).fillna(0).astype(int)
    scoped = scoped.sort_values("_flights", ascending=False)
    if top_n is not None:
        scoped = scoped.head(top_n)
    log.info(
        "Weather scope: %d airports in BTS data (of %d US airports)%s",
        len(scoped), len(airports),
        f"; capped to top {top_n} by volume" if top_n else "",
    )
    return scoped.drop(columns="_flights").reset_index(drop=True)


def ingest(
    settings: Settings,
    airports: pd.DataFrame,
    *,
    years: list[int] | None = None,
    overwrite: bool = False,
    scope_to_bts: bool = True,
    top_n: int | None = None,
) -> list[Path]:
    """Fetch + write hourly weather for the relevant airports.

    ``airports`` must have columns iata, lat, lon. By default the set is scoped
    to airports that appear in the bronze BTS data (``scope_to_bts``) — fetching
    all US airports blows Open-Meteo's free quota (see :func:`airports_in_bts`).
    ``top_n`` further caps to the busiest airports by flight volume.

    Partitioned by iata so reruns skip airports already present (resumable).
    Honors ``Retry-After`` and pauses between calls to stay under the limit.
    """
    years = years or BRONZE_YEARS
    start_date, end_date = _date_range(years)
    if scope_to_bts:
        airports = airports_in_bts(settings, airports, top_n=top_n)

    # If a previous run exhausted the daily quota, don't spam: probe ONCE to see
    # if it has reset. Still limited -> skip the weather stage cleanly so the
    # pipeline moves on (medallion left-joins weather, so partial is fine).
    # INGEST_FORCE_WEATHER=1 bypasses the cooldown probe entirely.
    import os
    force = os.environ.get("INGEST_FORCE_WEATHER", "").strip().lower() in {"1", "true", "yes"}
    if _cooldown_active(settings) and not overwrite and not force:
        if _probe_quota(settings, airports, start_date, end_date):
            _clear_cooldown(settings)
        else:
            remaining = _count_remaining(settings, airports, overwrite)
            log.warning(
                "Weather still rate-limited (cooldown active); skipping the "
                "weather stage. %d airport(s) remain — rerun after the Open-Meteo "
                "quota resets (≈ next UTC day). Set INGEST_FORCE_WEATHER=1 to "
                "override the probe.", remaining,
            )
            return []

    # Quota awareness (Open-Meteo free tier = 10,000 weighted calls/day; a
    # 4yr x 5var call ≈ 104 units, so ~90 airports/day). We stop cleanly at the
    # daily budget and resume next run — the backfill is resumable, so 200
    # airports complete over ~3 days. A consecutive-429 circuit breaker bails
    # fast when an earlier run already spent today's quota.
    budget = settings.weather_daily_budget
    abort_after = settings.weather_quota_abort_after

    written: list[Path] = []
    total = len(airports)
    fetched_today = 0
    consecutive_429 = 0

    with make_client(settings) as client:
        for i, row in enumerate(airports.itertuples(index=False), start=1):
            iata = row.iata
            out_file = _partition_file(settings, iata)
            if out_file.exists() and not overwrite:
                log.info("Skip weather %s (exists)", iata)
                continue

            if budget and fetched_today >= budget:
                remaining = _count_remaining(settings, airports, overwrite)
                log.warning(
                    "Weather daily budget reached (%d airports this run). "
                    "%d airport(s) still need weather — RERUN tomorrow to "
                    "resume (already-written airports are skipped).",
                    budget, remaining,
                )
                break

            try:
                df = fetch_airport(
                    settings, client, iata, row.lat, row.lon, start_date, end_date
                )
            except Exception as exc:  # noqa: BLE001 — keep going across airports
                consecutive_429 += 1
                log.error("Failed weather %s (%d/%d): %s", iata, i, total, exc)
                if abort_after and consecutive_429 >= abort_after:
                    remaining = _count_remaining(settings, airports, overwrite)
                    log.warning(
                        "Aborting weather stage: %d airports failed back-to-back "
                        "(Open-Meteo daily quota likely already spent). %d "
                        "airport(s) still need weather — RERUN after the quota "
                        "resets (≈ next UTC day); the next run probes once "
                        "instead of spamming.",
                        consecutive_429, remaining,
                    )
                    _write_cooldown(settings, remaining)
                    break
                continue

            consecutive_429 = 0
            out_file.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(out_file, index=False)
            fetched_today += 1
            log.info(
                "Wrote %s (%d hours) [%d/%d, %d/%d today]",
                out_file, len(df), i, total, fetched_today, budget,
            )
            time.sleep(settings.weather_pause_sec)
            written.append(out_file)
    return written


def _count_remaining(settings: Settings, airports: pd.DataFrame, overwrite: bool) -> int:
    """How many in-scope airports still lack a weather parquet (for log hints)."""
    if overwrite:
        return len(airports)
    return sum(
        1 for row in airports.itertuples(index=False)
        if not _partition_file(settings, row.iata).exists()
    )


# ----------------------------------------------------------------------
# Quota cooldown marker
# ----------------------------------------------------------------------
# Open-Meteo's 429 carries no Retry-After / reset timestamp, and the free daily
# quota resets on a wall-clock boundary we can't reliably compute. So instead of
# guessing when it clears, we record a cooldown marker and, on the next run, do a
# SINGLE probe to find out — succeed -> clear + proceed, 429 -> skip cleanly.

def _cooldown_path(settings: Settings) -> Path:
    return Path(settings.lake_root) / _COOLDOWN_FILE


def _write_cooldown(settings: Settings, remaining: int) -> None:
    p = _cooldown_path(settings)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "tripped_at": datetime.now(timezone.utc).isoformat(),
            "remaining_airports": remaining,
            "note": "Open-Meteo daily quota exhausted. Next run probes once; "
                    "rerun after the quota resets (≈ next UTC day).",
        }))
        log.info("Wrote weather quota cooldown marker -> %s", p)
    except OSError as exc:
        log.debug("Could not write cooldown marker (%s)", exc)


def _clear_cooldown(settings: Settings) -> None:
    p = _cooldown_path(settings)
    try:
        if p.exists():
            p.unlink()
            log.info("Cleared weather quota cooldown marker.")
    except OSError as exc:
        log.debug("Could not clear cooldown marker (%s)", exc)


def _cooldown_active(settings: Settings) -> dict | None:
    p = _cooldown_path(settings)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _probe_quota(settings: Settings, airports: pd.DataFrame,
                 start_date: str, end_date: str) -> bool:
    """One cheap call to see if the quota has reset. True = OK to proceed.

    Probes the first airport that still needs weather. We deliberately do a
    single try (no internal retries) so a still-exhausted quota fails fast.
    """
    pending = [r for r in airports.itertuples(index=False)
               if not _partition_file(settings, r.iata).exists()]
    if not pending:
        return True  # nothing to do; let the normal loop no-op
    row = pending[0]
    params = build_archive_params(row.lat, row.lon, start_date, end_date)
    try:
        with make_client(settings) as client:
            resp = get_with_retry(
                client, OPEN_METEO_ARCHIVE_URL,
                max_retries=0, pause=0.0, max_backoff=0.0, params=params,
            )
        # Persist the probe result so it isn't wasted: write that airport now.
        df = parse_archive_response(row.iata, resp.json())
        out_file = _partition_file(settings, row.iata)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_file, index=False)
        log.info("Quota probe OK (wrote %s) — proceeding with weather backfill.",
                 row.iata)
        return True
    except Exception as exc:  # noqa: BLE001 — probe failed = still limited
        log.warning("Quota probe failed (%s) — still rate-limited.", exc)
        return False
