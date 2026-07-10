"""flight_stream — the LIVE position path for the Flight Disruption Platform.

Pipeline: OpenSky (via ``flight_ingest``) -> NATS JetStream -> consumer ->
Valkey live cache, in the shape the serving API's ``/api/live/positions``
endpoint reads directly.

This is the *production-critical* live path. Kafka + Spark Structured Streaming
live under ``streaming/kafka_showcase`` as a separate build-once SHOWCASE and are
NOT part of this package.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
