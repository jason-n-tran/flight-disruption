# Kafka + Spark Structured Streaming Showcase

A real, runnable streaming pipeline that demonstrates **Kafka ingestion** and
**Spark Structured Streaming** (windowing + watermarking) on live flight data:

```
OpenSky US-bbox  ->  producer  ->  Kafka topic        ->  Spark Structured     ->  console + Parquet
(states/all)        (Python)      `flight-positions`     Streaming (windowed)     (+ optional Kafka
                                  on Redpanda            congestion agg)           topic `airport-congestion`)
```

## Honest framing

The **live demo** of the Flight Disruption Platform uses **NATS** (lightweight,
always-on) for its position stream — see `../flight_stream/`. **This Kafka+Spark
component is a build-once showcase**: it is genuinely runnable locally and proves
the Kafka / Spark Structured Streaming skill set, but it is **not** in the live
demo's critical path. Same OpenSky source, different transport, deliberately so.

## What it demonstrates

- `spark.readStream.format("kafka")` — Kafka as the ingestion buffer.
- `from_json` parsing against an explicit `StructType` schema that mirrors the
  producer's message contract 1:1 (`producer/messages.py` ↔
  `spark_app/streaming_job.py:MESSAGE_SCHEMA`).
- **Event-time** processing: the timestamp is the OpenSky snapshot `time`
  carried in each message (`event_ts`), not Spark's wall clock.
- `withWatermark(...)` to bound aggregation state and tolerate late data.
- `window(...)` tumbling (or sliding) aggregation: count of distinct aircraft
  per ~0.5° geo-cell → a live **airport-congestion** signal (busy terminal
  areas around major airports surface as high-count cells).
- Multiple streaming **sinks**: `console` (for the screenshot), `parquet`
  (durable), and optionally re-publishing back to a Kafka topic
  (`airport-congestion`).

## Prerequisites

- Docker (for Redpanda) — fits a 16GB machine (`--smp=1 --memory=1G`).
- Python 3.12, and the repo's shared packages installed:
  ```bash
  python -m pip install -r requirements.txt
  python -m pip install -e ../../ingestion -e ../../shared   # flight_ingest + flight_contracts
  ```
- For the Spark job: a JDK (Spark 3.5 needs Java 8/11/17) and `spark-submit` on
  PATH (installed with `pyspark`).
- Optional: OpenSky account creds for the 4000/day budget (anonymous = 400/day).
  Copy `.env.example` → `.env` and fill `OPENSKY_CLIENT_ID/SECRET`.

## Run it locally

All commands are run from this directory (`streaming/kafka_showcase/`).

### 1. Start Redpanda (+ console + topic creation)

```bash
docker compose -f docker-compose.kafka.yml up -d
```

- Kafka API (host): `localhost:19092`
- Redpanda console: <http://localhost:8080>
- The `topic-init` one-shot creates `flight-positions` and `airport-congestion`.

### 2. Run the producer (OpenSky → Kafka)

```bash
# load .env if you made one, then:
PYTHONIOENCODING=utf-8 python -m producer.producer
# bounded run for a quick screenshot:
PYTHONIOENCODING=utf-8 MAX_POLLS=5 python -m producer.producer
```

Each aircraft state is published as a JSON message keyed by `icao24` to
`flight-positions`. Watch messages arrive in the Redpanda console.

### 3. Run the Spark Structured Streaming job (Kafka → windowed congestion)

```bash
spark-submit \
  --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 \
  spark_app/streaming_job.py
```

The connector package version (`3.5.1`) must match the `pyspark` version in
`requirements.txt`. The job prints a windowed congestion table to the console
each trigger, writes finalized windows to `./data/congestion_parquet`, and (if
`WRITE_KAFKA=true`) re-publishes them to `airport-congestion`.

### 4. (Optional) run everything via env file

Every setting is env-driven (`.env.example`): window/slide/watermark durations,
cell size, bootstrap servers, topics, poll cadence, sinks.

## Screenshot checklist (for the README claims)

1. **Redpanda console** (`localhost:8080`) → Topics → `flight-positions`
   showing messages flowing in (key = icao24, JSON value).
2. **Producer logs** — `Snapshot @… : N aircraft -> M messages on 'flight-positions'`.
3. **Spark streaming query progress** — the `console` sink's windowed congestion
   table (`window_start`, `window_end`, `cell_lat`, `cell_lon`, `aircraft_count`)
   sorted by count, plus a `StreamingQueryProgress` log line.
4. **Output** — `./data/congestion_parquet` files, or (if enabled) the
   `airport-congestion` topic in the console.

## Validation (no broker / cluster needed here)

The streaming pipeline can't be run end-to-end in CI without a broker + Spark,
so correctness is pinned by:

```bash
python -m py_compile producer/producer.py spark_app/streaming_job.py
python -m pytest -q          # broker-free unit tests (messages, geo, producer)
```

The unit tests cover the JSON (de)serialization contract, the geo-cell binning
that the Spark SQL aggregation mirrors, and `publish_snapshot` against a fake
KafkaProducer.

## Files

| Path | Purpose |
|------|---------|
| `producer/producer.py` | OpenSky poll loop → Kafka `flight-positions` (reuses `flight_ingest`). |
| `producer/messages.py` | Broker-free message build/serialize contract. |
| `producer/config.py` | Env-driven producer settings. |
| `spark_app/streaming_job.py` | Spark Structured Streaming: Kafka → windowed congestion. |
| `spark_app/geo.py` | Geo-cell binning helpers (mirrored by the Spark SQL). |
| `docker-compose.kafka.yml` | Redpanda + console + topic init. |
| `tests/` | Broker-free unit tests. |
| `.env.example` | All config knobs. |

## Tuning for a 16GB machine

Redpanda runs single-core / 1 GiB (dev-container mode). Spark uses
`spark.sql.shuffle.partitions=8` and local mode. Lower `WINDOW_DURATION` /
raise `MIN_CONGESTION_COUNT` to keep the console output compact.
