"""
Structured JSON logging infrastructure.

Provides consistent JSON-formatted log output with rotating file storage
and process/request tracking for telemetry pipelines.

The implementation supports:

    - Line-delimited JSON log output
    - Timed rotating log files with automatic gzip compression
    - Distributed tracing via request_id correlation

Key classes / functions:

    - JsonFormatter: Custom log formatter generating single-line JSON records.
    - configure_logging: Set up service root logger with rotating file handler.

"""

import json
import logging
import logging.handlers
import os
import uuid
from pathlib import Path

_PROCESS_ID = str(uuid.uuid4())


class JsonFormatter(logging.Formatter):
    """
    Render log records as single-line JSON strings with structured fields.

    Extracts standard log record attributes, attaches process and request identifiers,
    and formats exceptions into structured JSON payloads.

    Args:
        service (str): Name of the service emitting the log records.

    """

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the specified log record into a single JSON line.

        Args:
            record (logging.LogRecord): Log record containing event data.

        Returns:
            str: JSON-encoded string representation of the log entry.

        """
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "request_id": getattr(record, "request_id", _PROCESS_ID),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Allow callers to attach arbitrary structured fields via `extra=`.
        for key, value in record.__dict__.items():
            if key in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process",
                "request_id", "message", "asctime",
            ):
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(service: str, log_dir: str = None) -> logging.Logger:
    """
    Configure the root logger for a service with daily-rotating JSON file output.

    Attaches a TimedRotatingFileHandler that rotates daily at midnight, keeps
    10 days of backups, and compresses rotated files using gzip.

    Args:
        service (str): Identifying name of the service (e.g., 'kafka-consumer').
        log_dir (str, optional): Directory path where logs will be written. Defaults to $LOG_DIR or './logs'.

    Returns:
        logging.Logger: Configured logger instance for the given service name.

    Example:
        >>> log = configure_logging("test-service", log_dir="/tmp/logs")
        >>> log.info("Service initialized")

    """
    log_dir = log_dir or os.environ.get("LOG_DIR", "./logs")
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "app.log"

    formatter = JsonFormatter(service)

    # Daily rotation, keep 10 days, compress rotated files.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=10,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"
    file_handler.rotator = _gzip_rotator

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if configure_logging() is called twice
    # (e.g. reimported in tests).
    root.handlers.clear()
    root.addHandler(file_handler)

    return logging.getLogger(service)



def _gzip_rotator(source: str, dest: str) -> None:
    """TimedRotatingFileHandler rotator that gzip-compresses old log files."""
    import gzip
    import shutil

    with open(source, "rb") as f_in, gzip.open(f"{dest}.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(source)
