# Live position stream: OpenSky -> NATS JetStream -> Valkey.
#
# BUILD CONTEXT = REPO ROOT (the root docker-compose `live-stream` service uses
# `context: .` with `dockerfile: streaming/Dockerfile`) so we can COPY the
# sibling path packages (shared/, ingestion/) this package depends on.
#
#   docker build -f streaming/Dockerfile -t flight-live-stream .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Path dependencies first (better layer caching).
COPY shared/ /app/shared/
COPY ingestion/ /app/ingestion/
COPY streaming/ /app/streaming/

# Install the local packages (and their pinned deps: nats-py, redis, httpx).
RUN pip install --upgrade pip \
 && pip install -e /app/shared -e /app/ingestion -e /app/streaming

# Default to the single-container combined mode (producer + consumer).
CMD ["python", "-m", "flight_stream.run", "both"]
