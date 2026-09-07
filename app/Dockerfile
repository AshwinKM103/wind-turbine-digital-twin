# Wind Turbine Digital Twin - producer/consumer image
# The entrypoint script is selected per service via `command:` in
# docker-compose.yml.
FROM python:3.11-slim

# curl: required by the docker-compose healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    LOG_DIR=/app/logs

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/logs /app/data \
    && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/src
