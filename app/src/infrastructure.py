"""Infrastructure module combining structured logging and HTTP health endpoints."""

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
    """Renders each log record as one JSON object per line."""

    def __init__(self, service: str):
        """Initialize JSON formatter with service identifier."""
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a structured JSON string."""
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
    """TimedRotatingFileHandler rotator that gzip-compresses old log files."""
    with open(source, "rb") as f_in, gzip.open(f"{dest}.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.remove(source)


def configure_logging(service: str, log_dir: Optional[str] = None) -> logging.Logger:
    """Configure root logger for a service with daily-rotating JSON file output.

    Writes compressed daily backups to LOG_DIR (defaults to ./logs or $LOG_DIR).
    """
    log_dir = log_dir or os.environ.get("LOG_DIR", "./logs")
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = JsonFormatter(service)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if configure_logging() is called twice
    # (e.g. reimported in tests).
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
    """Thread-safe status container shared with the health HTTP handler."""

    def __init__(self) -> None:
        """Initialize health state tracking locks and checks dictionary."""
        self._lock = threading.Lock()
        self._checks: Dict[str, Dict[str, str]] = {}
        self._ready: bool = False

    def set_check(self, name: str, ok: bool, detail: str = "") -> None:
        """Update the status of an individual health check."""
        with self._lock:
            self._checks[name] = {"status": "ok" if ok else "fail", "detail": detail}

    def set_ready(self, ready: bool) -> None:
        """Update the readiness status of the service."""
        with self._lock:
            self._ready = ready

    def snapshot(self) -> Tuple[Dict[str, Dict[str, str]], bool]:
        """Return a copy of current health checks and readiness state."""
        with self._lock:
            return dict(self._checks), self._ready


def _make_handler(state: HealthState, service_name: str):
    """Construct HTTP request handler bound to the specified health state."""
    class Handler(BaseHTTPRequestHandler):
        """HTTP handler serving /health and /ready probe endpoints."""

        def _write_json(self, status_code: int, payload: Dict[str, Any]) -> None:
            """Serialize payload to JSON and write HTTP response."""
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            """Handle GET requests for /health liveness and /ready readiness probes."""
            if self.path == "/health":
                # Liveness check: confirms process is responsive
                self._write_json(200, {"status": "healthy", "service": service_name})
            elif self.path == "/ready":
                checks, ready = state.snapshot()
                overall = "healthy" if ready and all(c["status"] == "ok" for c in checks.values()) else "unhealthy"
                code = 200 if overall == "healthy" else 503
                self._write_json(code, {"status": overall, "checks": checks})
            else:
                self._write_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: Any) -> None:
            """Suppress default HTTP access logs."""
            pass

    return Handler


def start_health_server(port: int, service_name: str) -> HealthState:
    """Starts the health server in a daemon thread and returns its shared state."""
    state = HealthState()
    handler_cls = _make_handler(state, service_name)
    server = HTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    log.info("Health server listening on :%d (/health, /ready)", port)
    return state
