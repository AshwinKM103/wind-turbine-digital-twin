"""
config.py - Centralized environment-variable configuration.

All runtime configuration (hosts, ports, credentials, tuning knobs) comes
from environment variables, which docker-compose populates from the
.env file for the active environment (see .env.example). Nothing here is
hardcoded, so the same image runs unmodified in dev/staging/production --
only the .env file changes. Never hardcode secrets in code (see
/home/ashwinkm/.claude/rules/security.md).
"""

import os

try:
    # Convenience for running the scripts outside Docker (docker-compose
    # itself injects .env values as real environment variables, so this
    # is a no-op there). Never required in production containers.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid int") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid float") from exc


class Config:
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS_INTERNAL") or os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"
    )
    KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "turbine.telemetry.raw.v1")
    KAFKA_GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "iotdb-writer-group")
    DLQ_TOPIC = os.environ.get("DLQ_TOPIC", "turbine.telemetry.dlq")

    # IoTDB
    IOTDB_HOST = os.environ.get("IOTDB_HOST", "iotdb")
    IOTDB_PORT = _get_int("IOTDB_PORT", 6667)
    IOTDB_USER = os.environ.get("IOTDB_USER", "root")
    IOTDB_PASSWORD = os.environ.get("IOTDB_PASSWORD", "root")

    # Device / topology
    CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "customer1")
    SITE_ID = os.environ.get("SITE_ID", "site1")
    TURBINE_ID = os.environ.get("TURBINE_ID", "turbine01")
    DEVICE_PATH_ROOT = os.environ.get("DEVICE_PATH_ROOT", "root.digitaltwin")
    # Fallback device path only -- the multi-turbine consumer derives the
    # real path per message from the payload's customer_id/turbine_id (see
    # kafka_consumer.device_path_for). This stays for single-turbine
    # deployments and for logging the consumer's default tenant.
    DEVICE_PATH = os.environ.get(
        "DEVICE_PATH", f"{DEVICE_PATH_ROOT}.{CUSTOMER_ID}.{SITE_ID}.{TURBINE_ID}"
    )

    # Producer tuning
    SAMPLE_INTERVAL_S = _get_float("SAMPLE_INTERVAL_S", 1.0)
    PRODUCE_LOG_EVERY_N = _get_int("PRODUCE_LOG_EVERY_N", 30)

    # Synthetic generator state machine (seconds per operating state).
    # Defaults give a ~14-minute cycle: long enough that STEADY_STATE
    # dominates (as in a real duty cycle), short enough that a demo sees
    # every state within one dashboard session.
    STATE_IDLE_DURATION_S = _get_float("STATE_IDLE_DURATION_S", 60.0)
    STATE_RAMP_UP_DURATION_S = _get_float("STATE_RAMP_UP_DURATION_S", 120.0)
    STATE_STEADY_DURATION_S = _get_float("STATE_STEADY_DURATION_S", 600.0)
    STATE_RAMP_DOWN_DURATION_S = _get_float("STATE_RAMP_DOWN_DURATION_S", 90.0)

    # Sensor display-name / unit metadata (generated from sensor_profiles.py)
    SENSOR_MAPPINGS_PATH = os.environ.get(
        "SENSOR_MAPPINGS_PATH", "/app/config/sensor_mappings.json"
    )

    # Consumer tuning
    BATCH_SIZE = _get_int("BATCH_SIZE", 50)
    BATCH_MAX_WAIT_S = _get_float("BATCH_MAX_WAIT_S", 5.0)
    IOTDB_WRITE_MAX_RETRIES = _get_int("IOTDB_WRITE_MAX_RETRIES", 3)
    IOTDB_WRITE_BACKOFF_BASE_S = _get_float("IOTDB_WRITE_BACKOFF_BASE_S", 0.2)

    # Circuit breaker (IoTDB connection protection)
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = _get_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)
    CIRCUIT_BREAKER_RESET_TIMEOUT_S = _get_float("CIRCUIT_BREAKER_RESET_TIMEOUT_S", 30.0)

    # Health check server
    HEALTH_CHECK_PORT = _get_int("HEALTH_CHECK_PORT", 8000)

    # Logging
    LOG_DIR = os.environ.get("LOG_DIR", "./logs")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
