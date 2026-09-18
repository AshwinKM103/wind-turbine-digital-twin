"""Centralized environment-variable configuration for runtime services."""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _get_int(name: str, default: int) -> int:
    """Parse an integer environment variable with fallback."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid int") from exc


def _get_float(name: str, default: float) -> float:
    """Parse a float environment variable with fallback."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid float") from exc


def _get_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable with fallback."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalised = raw.strip().lower()
    if normalised in ("1", "true", "yes", "on"):
        return True
    if normalised in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Environment variable {name}={raw!r} is not a valid boolean")


class ConfigError(Exception):
    """A required setting is missing or self-contradictory."""


class Config:
    """Runtime configuration loaded from environment variables."""
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS_INTERNAL") or os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"
    )
    KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "turbine.telemetry.raw.v1")
    KAFKA_GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "iotdb-writer-group")
    DLQ_TOPIC = os.environ.get("DLQ_TOPIC", "turbine.telemetry.dlq")

    # IoTDB
    IOTDB_HOST = os.environ.get("IOTDB_HOST", "localhost")
    IOTDB_PORT = _get_int("IOTDB_PORT", 6667)
    IOTDB_USER = os.environ.get("IOTDB_USER", "root")
    IOTDB_PASSWORD = os.environ.get("IOTDB_PASSWORD", "root")

    # Postgres (alerts + turbine state history; see postgres_store.py)
    POSTGRES_ENABLED = _get_bool("POSTGRES_ENABLED", True)
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = _get_int("POSTGRES_PORT", 5432)
    POSTGRES_DB = os.environ.get("POSTGRES_DB", "turbine")
    POSTGRES_USER = os.environ.get("POSTGRES_USER", "turbine")
    POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
    POSTGRES_RETENTION_DAYS = _get_int("POSTGRES_RETENTION_DAYS", 30)
    POSTGRES_QUEUE_SIZE = _get_int("POSTGRES_QUEUE_SIZE", 10000)

    # Turbine state timeline
    STATE_STABILITY_SECONDS = _get_float("STATE_STABILITY_SECONDS", 30.0)
    STATE_STALE_SECONDS = _get_float("STATE_STALE_SECONDS", 120.0)

    # Device / topology
    CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "customer1")
    SITE_ID = os.environ.get("SITE_ID", "site1")
    TURBINE_ID = os.environ.get("TURBINE_ID", "turbine01")
    DEVICE_PATH_ROOT = os.environ.get("DEVICE_PATH_ROOT", "root.digitaltwin")
    DEVICE_PATH = os.environ.get(
        "DEVICE_PATH", f"{DEVICE_PATH_ROOT}.{CUSTOMER_ID}.{SITE_ID}.{TURBINE_ID}"
    )

    # Producer tuning
    SAMPLE_INTERVAL_S = _get_float("SAMPLE_INTERVAL_S", 1.0)
    PRODUCE_LOG_EVERY_N = _get_int("PRODUCE_LOG_EVERY_N", 30)

    # Synthetic generator state machine durations (seconds)
    STATE_IDLE_DURATION_S = _get_float("STATE_IDLE_DURATION_S", 60.0)
    STATE_RAMP_UP_DURATION_S = _get_float("STATE_RAMP_UP_DURATION_S", 120.0)
    STATE_STEADY_DURATION_S = _get_float("STATE_STEADY_DURATION_S", 600.0)
    STATE_RAMP_DOWN_DURATION_S = _get_float("STATE_RAMP_DOWN_DURATION_S", 90.0)

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
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG")

    @classmethod
    def postgres_dsn(cls) -> str:
        """libpq connection string for the alert/state store."""
        from urllib.parse import quote

        user = quote(cls.POSTGRES_USER, safe="")
        password = quote(cls.POSTGRES_PASSWORD, safe="")
        return (
            f"postgresql://{user}:{password}@"
            f"{cls.POSTGRES_HOST}:{cls.POSTGRES_PORT}/{cls.POSTGRES_DB}"
        )

    @classmethod
    def validate_postgres(cls) -> None:
        """Validate Postgres environment variables when enabled."""
        if not cls.POSTGRES_ENABLED:
            return
        missing = [
            name
            for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
            if not getattr(cls, name)
        ]
        if missing:
            raise ConfigError(
                "POSTGRES_ENABLED is true but "
                + ", ".join(missing)
                + " is unset. Set it in .env (see .env.example), or set "
                "POSTGRES_ENABLED=false to run without alert persistence."
            )
        if not 1 <= cls.POSTGRES_PORT <= 65535:
            raise ConfigError(f"POSTGRES_PORT={cls.POSTGRES_PORT} is not a valid TCP port")
        if cls.POSTGRES_RETENTION_DAYS < 1:
            raise ConfigError(
                f"POSTGRES_RETENTION_DAYS={cls.POSTGRES_RETENTION_DAYS} would delete "
                "data as fast as it is written"
            )
        if cls.STATE_STALE_SECONDS <= cls.STATE_STABILITY_SECONDS:
            raise ConfigError(
                f"STATE_STALE_SECONDS ({cls.STATE_STALE_SECONDS}) must exceed "
                f"STATE_STABILITY_SECONDS ({cls.STATE_STABILITY_SECONDS}); otherwise "
                "every turbine is marked DOWN before its first state is confirmed"
            )
