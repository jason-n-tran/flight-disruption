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
