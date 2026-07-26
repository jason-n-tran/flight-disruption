# Serving API image. BUILD CONTEXT = REPO ROOT (see docker-compose.yml:
#   build: { context: ., dockerfile: serving/Dockerfile })
# so it can COPY the shared contracts, the consumed packages, and bake the
# bundled sample artifacts -> the image is fully self-contained (offline demo).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for any wheels that need compiling (lightgbm needs libgomp at runtime).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# --- source: the packages the serving layer imports + itself ---
# Copied before the heavy pip install so layer caching works on code-only changes.
COPY shared/ /app/shared/
COPY ml/ /app/ml/
COPY ingestion/ /app/ingestion/
COPY serving/ /app/serving/

# Install the three path deps + the serving package (pulls fastapi/uvicorn/duckdb/
# redis/boto3/httpx/pandas/numpy + lightgbm/shap from the ml package).
RUN pip install ./shared ./ml ./ingestion ./serving

# --- bake the bundled sample artifacts so the image runs offline ---
# Default DUCKDB_PATH/MODEL_PATH point at /artifacts; copy the sample there.
COPY data/sample/ /artifacts/
COPY data/sample/ /app/data/sample/

ENV DUCKDB_PATH=/artifacts/gold.duckdb \
    MODEL_PATH=/artifacts/model.lgb \
    SAMPLE_DIR=/app/data/sample \
    DATA_VERSION=sample \
    VALKEY_HOST=valkey \
    VALKEY_PORT=6379 \
    ALLOWED_ORIGINS=http://localhost:5173,http://localhost:4173

EXPOSE 8005

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8005/health').status==200 else 1)"

CMD ["uvicorn", "flight_serving.app:app", "--host", "0.0.0.0", "--port", "8005"]
