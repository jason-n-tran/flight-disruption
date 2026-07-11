"""Env-driven config for the Kafka showcase producer.

Defaults make a fresh clone runnable against the bundled docker-compose Redpanda
(``localhost:19092``). Missing OpenSky creds degrade to anonymous fetches inside
``flight_ingest`` — the showcase still runs, just on the 400/day anon budget.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class ProducerSettings:
    """Resolved producer settings.

    Attributes
    ----------
    bootstrap_servers:
        Kafka/Redpanda bootstrap. Default ``localhost:19092`` matches the
        external listener exposed by ``docker-compose.kafka.yml``.
    topic:
        Destination topic for per-aircraft position events.
    poll_interval_seconds:
        Sleep between OpenSky snapshots. Default 60s — one US-bbox call costs 4
        OpenSky credits, so 60s is well within the authenticated 4000/day budget
        for a screenshot session. This is a build-once showcase, not 24/7.
    max_polls:
        Stop after N snapshots (0 = run forever). Lets a screenshot run be
        bounded, e.g. ``MAX_POLLS=10``.
    client_id:
        Kafka client id (shows up in Redpanda console / metrics).
    """

    bootstrap_servers: str
    topic: str
    poll_interval_seconds: float
    max_polls: int
    client_id: str


def load_settings() -> ProducerSettings:
    return ProducerSettings(
        bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
        topic=os.environ.get("KAFKA_TOPIC", "flight-positions"),
        poll_interval_seconds=_env_float("POLL_INTERVAL_SECONDS", 60.0),
        max_polls=_env_int("MAX_POLLS", 0),
        client_id=os.environ.get("KAFKA_CLIENT_ID", "flight-kafka-showcase-producer"),
    )
