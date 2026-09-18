"""
logging_config.py - Shared structured (JSON) logging setup.

Emits the same log shape as infrastructure.py's configure_logging: a
rotating JSON file under LOG_DIR (default: /app/logs, i.e. ./app/logs on
the host), file only.

Every record includes: timestamp, level, service, request_id, message.
request_id defaults to a per-process id but callers can pass a per-message
one via `extra={"request_id": ...}` to correlate a single telemetry
message across producer -> Kafka -> consumer -> IoTDB.
"""

import json
import logging
import logging.handlers
import os
import uuid
from pathlib import Path

_PROCESS_ID = str(uuid.uuid4())


class JsonFormatter(logging.Formatter):
    """Renders each log record as one JSON object per line."""

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
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
    Configure the root logger for `service` with a rotating file handler:
    daily rotation, 10 backups kept, gzip'd.

    log_dir defaults to $LOG_DIR or ./logs relative to cwd, matching the
    LOG_DIR env var wired up in docker-compose.yml (/app/logs inside each
    container, bind-mounted from ./app/logs on the host).
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
