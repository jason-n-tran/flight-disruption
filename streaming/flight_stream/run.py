"""Entrypoint: ``python -m flight_stream.run {producer|consumer|both}``.

* ``producer`` — poll OpenSky and publish to NATS only.
* ``consumer`` — subscribe to NATS and write Valkey only.
* ``both``     — run both in one asyncio process (the simple single-container
  deploy used by the compose ``live-stream`` service). They stay separable so
  they can scale to distinct processes/containers later.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import load_settings
from .consumer import run_consumer
from .producer import run_producer

VALID_MODES = {"producer", "consumer", "both"}


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows: add_signal_handler unsupported for SIGTERM; SIGINT still
            # raises KeyboardInterrupt which we catch in main().
            pass


async def _run(mode: str) -> None:
    settings = load_settings()
    stop = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), stop)

    if mode == "producer":
        await run_producer(settings, stop=stop)
    elif mode == "consumer":
        await run_consumer(settings, stop=stop)
    else:  # both
        await asyncio.gather(
            run_producer(settings, stop=stop),
            run_consumer(settings, stop=stop),
        )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "both"
    if mode not in VALID_MODES:
        print(f"usage: python -m flight_stream.run {{{'|'.join(sorted(VALID_MODES))}}}")
        return 2

    log = logging.getLogger("flight_stream.run")
    log.info("Starting flight_stream in mode=%s", mode)
    try:
        asyncio.run(_run(mode))
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
