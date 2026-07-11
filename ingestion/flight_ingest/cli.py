"""Command-line entry point: ``python -m flight_ingest.cli <command>``.

Commands: ``bts``, ``weather``, ``airports``, ``opensky-snapshot``, ``all``.
"""

from __future__ import annotations

import argparse
import logging
import sys

from flight_contracts import BRONZE_YEARS

from . import bts, openflights, opensky, weather
from .config import load_settings


def _parse_int_list(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flight_ingest",
        description="Ingest BTS / Open-Meteo / OpenFlights / OpenSky into bronze.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-ingest even if the parquet partition already exists.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    bts_p = sub.add_parser("bts", help="Download BTS On-Time Performance months.")
    bts_p.add_argument("--years", help="Comma list, e.g. 2022,2023 (default BRONZE_YEARS).")
    bts_p.add_argument("--months", help="Comma list 1-12 (default all 12).")

    w_p = sub.add_parser("weather", help="Open-Meteo archive per airport.")
    w_p.add_argument("--years", help="Comma list for date range (default BRONZE_YEARS).")
    w_p.add_argument(
        "--top-n", type=int, default=None,
        help="Cap to the busiest N airports by BTS flight volume (default: all "
             "airports present in BTS).",
    )
    w_p.add_argument(
        "--no-scope", action="store_true",
        help="Fetch ALL US airports instead of just those in BTS (will likely "
             "hit Open-Meteo rate limits).",
    )

    sub.add_parser(
        "repair-weather",
        help="Rewrite existing weather parquet from ns->us timestamps (Spark 3.5 "
             "can't read TIMESTAMP(NANOS)). Idempotent; no re-fetch.",
    )

    sub.add_parser(
        "reschema-bts",
        help="Rewrite existing BTS parquet with the stable enforced schema "
             "(fixes cross-month int/double drift). Idempotent; no re-download.",
    )

    sub.add_parser("airports", help="Download + filter OpenFlights airport dim.")

    snap_p = sub.add_parser("opensky-snapshot", help="One-shot US-bbox snapshot.")
    snap_p.add_argument(
        "--out",
        default="./data/samples/live_positions_sample.json",
        help="Where to write the sample JSON.",
    )

    all_p = sub.add_parser("all", help="airports -> bts -> weather -> opensky snapshot.")
    all_p.add_argument("--years", help="Comma list applied to bts + weather.")
    all_p.add_argument("--months", help="Comma list for bts.")
    all_p.add_argument(
        "--top-n", type=int, default=None,
        help="Cap weather to the busiest N airports by BTS flight volume.",
    )
    all_p.add_argument(
        "--snapshot-out",
        default="./data/samples/live_positions_sample.json",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    settings = load_settings()
    log = logging.getLogger("flight_ingest.cli")

    if args.command == "bts":
        written = bts.ingest(
            settings,
            years=_parse_int_list(args.years),
            months=_parse_int_list(args.months),
            overwrite=args.overwrite,
        )
        log.info("BTS: wrote %d partitions", len(written))

    elif args.command == "weather":
        airports = openflights.load_airports(settings)
        written = weather.ingest(
            settings,
            airports,
            years=_parse_int_list(args.years),
            overwrite=args.overwrite,
            scope_to_bts=not args.no_scope,
            top_n=args.top_n,
        )
        log.info("Weather: wrote %d airport series", len(written))

    elif args.command == "repair-weather":
        n = weather.repair_timestamp_precision(settings)
        log.info("Weather repair: rewrote %d file(s) ns->us", n)

    elif args.command == "reschema-bts":
        n = bts.reschema_existing(settings)
        log.info("BTS reschema: rewrote %d partition(s)", n)

    elif args.command == "airports":
        path = openflights.ingest(settings, overwrite=args.overwrite)
        log.info("Airports: %s", path)

    elif args.command == "opensky-snapshot":
        path = opensky.write_sample(settings, args.out)
        log.info("OpenSky snapshot: %s", path)

    elif args.command == "all":
        years = _parse_int_list(args.years) or BRONZE_YEARS
        openflights.ingest(settings, overwrite=args.overwrite)
        bts.ingest(
            settings,
            years=years,
            months=_parse_int_list(args.months),
            overwrite=args.overwrite,
        )
        airports = openflights.load_airports(settings)
        weather.ingest(
            settings, airports, years=years, overwrite=args.overwrite,
            scope_to_bts=True, top_n=args.top_n,
        )
        try:
            opensky.write_sample(settings, args.snapshot_out)
        except Exception as exc:  # noqa: BLE001 — snapshot is best-effort
            log.warning("OpenSky snapshot skipped: %s", exc)

    else:  # pragma: no cover — argparse enforces required subcommand
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
