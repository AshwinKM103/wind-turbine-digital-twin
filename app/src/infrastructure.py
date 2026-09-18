"""
Infrastructure module combining structured logging and HTTP health endpoints.

Provides service logging configuration with JSON formatting, timed rotation,
and background daemon HTTP probe endpoints (/health and /ready).

The implementation supports:

    - Daily rotating JSON log files with gzip compression
    - Thread-safe health and readiness state management
    - Standard HTTP health endpoints for orchestrator probes

Key classes / functions:

    - JsonFormatter: Custom log formatter generating single-line JSON records.
    - configure_logging: Set up service root logger with rotating file handler.
    - HealthState: Thread-safe status container for service probes.
    - start_health_server: Start daemon thread HTTP health probe server.

"""

from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_PROCESS_ID = str(uuid.uuid4())
log = logging.getLogger("health")


class JsonFormatter(logging.Formatter):
    """
    Render log records as single-line JSON strings with structured fields.

    Args:
        service (str): Service name identifier included in every log entry.

    """

    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a single log record into a JSON string.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: JSON-encoded string representation.

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


def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as f_in, gzip.open(f"{dest}.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(source)


def configure_logging(service: str, log_dir: Optional[str] = None) -> logging.Logger:
    """
    Configure root logger for a service with daily-rotating JSON file output.

    Args:
        service (str): Identifying name of the service.
        log_dir (Optional[str], optional): Target log directory. Defaults to $LOG_DIR or './logs'.

    Returns:
        logging.Logger: Root logger configured for the specified service.

    Example:
        >>> logger = configure_logging("my-service", log_dir="/tmp/logs")
        >>> logger.info("Service initialized")

    """
    log_dir = log_dir or os.environ.get("LOG_DIR", "./logs")
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = JsonFormatter(service)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "app.log"

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
    root.addHandler(file_handler)

    return logging.getLogger(service)


class HealthState:
    """
    Thread-safe status container shared with the health HTTP handler.

    Maintains component health checks and readiness flags, synchronizing access
    with a reentrant-safe mutex.

    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checks: Dict[str, Dict[str, str]] = {}
        self._ready: bool = False

    def set_check(self, name: str, ok: bool, detail: str = "") -> None:
        """
        Update the status of an individual health check.

        Args:
            name (str): Identifier of the component or check.
            ok (bool): True if healthy, False otherwise.
            detail (str, optional): Diagnostic explanation. Defaults to "".

        """
        with self._lock:
            self._checks[name] = {"status": "ok" if ok else "fail", "detail": detail}

    def set_ready(self, ready: bool) -> None:
        """
        Update the readiness status of the service.

        Args:
            ready (bool): True if service is ready to handle traffic, False otherwise.

        """
        with self._lock:
            self._ready = ready

    def snapshot(self) -> Tuple[Dict[str, Dict[str, str]], bool]:
        """
        Return a copy of current health checks and readiness state.

        Returns:
            Tuple[Dict[str, Dict[str, str]], bool]: Atomic snapshot of checks and readiness.

        """
        with self._lock:
            return dict(self._checks), self._ready


def _make_handler(state: HealthState, service_name: str):
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write_json(200, {"status": "healthy", "service": service_name})
            elif self.path == "/ready":
                checks, ready = state.snapshot()
                overall = "healthy" if ready and all(c["status"] == "ok" for c in checks.values()) else "unhealthy"
                code = 200 if overall == "healthy" else 503
                self._write_json(code, {"status": overall, "checks": checks})
            else:
                self._write_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def start_health_server(port: int, service_name: str) -> HealthState:
    """
    Start the health server in a daemon thread and return its shared state.

    Args:
        port (int): Port number on which to bind the HTTP probe server.
        service_name (str): Identifying service name reported in responses.

    Returns:
        HealthState: Mutable container for updating check results and readiness.

    Example:
        >>> health = start_health_server(8080, "my-service")
        >>> health.set_ready(True)

    """
    state = HealthState()
    handler_cls = _make_handler(state, service_name)
    server = HTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    log.info("Health server listening on :%d (/health, /ready)", port)
    return state

