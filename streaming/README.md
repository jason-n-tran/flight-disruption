# streaming/ — live position path (`flight_stream`)

The **production-critical live view** for the Flight Disruption Platform map:

```
OpenSky  --poll-->  producer  --publish-->  NATS JetStream  --consume-->  consumer  --write-->  Valkey
(states/all)                  (flight.positions)                                    (flight:positions:*)
```

The serving API's `GET /api/live/positions` reads the Valkey keys this consumer
writes — no transform happens at serve time.

## NATS live vs Kafka showcase

This package (`flight_stream`) is the **lightweight, always-on live path** using
**NATS JetStream**. It is the path the demo actually depends on. The
**Kafka + Spark Structured Streaming** build under `streaming/kafka_showcase/` is
a separate **build-once SHOWCASE** (different agent) that demonstrates breadth;
the live demo never depends on it. Two implementations, one architectural point:
choose the right tool per job (NATS = simple/cheap live cache feed; Kafka/Spark
= the "I can do big-data streaming too" artifact).

## Viewer-gated polling (why, and the credit math)

OpenSky's free budget: anonymous = **400 credits/day**, registered = **4000/day**.
A US-bbox `states/all` call costs **4 credits**, so 4000 / 4 = **~1000 calls/day**
— one call every ~86s if polling 24/7. A flat 60s poll would blow the budget.

**Solution:** poll fast only when someone is looking at the map. The serving API
writes `flight:viewer:last_seen` (epoch seconds) on each live request. Each cycle
the producer reads that key: if a viewer was seen within
`VIEWER_ACTIVE_WINDOW_SECONDS` it polls at `POLL_INTERVAL_SECONDS` (60s); if not,
it backs off to `IDLE_INTERVAL_SECONDS` (600s) and **skips the OpenSky call
entirely** — no credits spent refreshing a map nobody is watching.

## Modes

```bash
python -m flight_stream.run producer   # OpenSky -> NATS only
python -m flight_stream.run consumer   # NATS -> Valkey only
python -m flight_stream.run both       # both in one asyncio process (default)
```

`both` is the simple single-container deploy (the compose `live-stream` service,
profile `live`); producer and consumer stay separable for horizontal scale.

## Resilience

- OAuth token cached and refreshed before expiry (`oauth.TokenCache`); missing
  creds degrade to anonymous, never crash.
- Every network/broker error is logged and the loop continues — the producer is
  designed to be unkillable.
- `429` honors `Retry-After`; `X-Rate-Limit-Remaining` is logged each call.
- Valkey holds both a short-TTL live key and a long-TTL `cached` fallback so the
  map is never empty even if OpenSky/the producer go down.

## Valkey keys (all `flight:`-prefixed via `flight_contracts.valkey_key`)

| key | TTL | writer | meaning |
|-----|-----|--------|---------|
| `flight:positions:latest` | `POSITIONS_TTL_SECONDS` (300s) | consumer | live snapshot (`source:"live"`) |
| `flight:positions:cached` | `POSITIONS_CACHED_TTL_SECONDS` (86400s) | consumer | fallback snapshot (`source:"cached"`) |
| `flight:viewer:last_seen` | — | **serving API** (read here) | epoch secs of last live request |

## Environment variables

See [`.env.example`](.env.example). Key ones:
`NATS_URL`, `NATS_SUBJECT`, `VALKEY_HOST`/`VALKEY_PORT`,
`POLL_INTERVAL_SECONDS`, `IDLE_INTERVAL_SECONDS`, `VIEWER_ACTIVE_WINDOW_SECONDS`,
`OPENSKY_CLIENT_ID`/`OPENSKY_CLIENT_SECRET`, `INGEST_SSL_VERIFY`.

## Develop / test

```bash
pip install -e ../shared -e ../ingestion -e .
python -m pytest -q
```

Tests mock NATS, Valkey (fakeredis), and OpenSky — no network or broker needed.

## Docker

Build context is the **repo root** (so `shared/` + `ingestion/` are available):

```bash
docker build -f streaming/Dockerfile -t flight-live-stream .
# or, from the root compose:
docker compose --profile live up live-stream
```
