"""
health_server.py - Minimal /health and /ready HTTP endpoints.

Runs in a background thread inside synthetic_producer.py / kafka_consumer.py so
docker-compose healthchecks (curl -f http://localhost:PORT/health) and
external monitoring can check liveness/readiness without an extra
process. Responds within milliseconds and performs no expensive work,
per the health-check convention this project follows.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("health")


class HealthState:
    """Thread-safe mutable status shared between the app's main loop and
    the health HTTP handler."""

    def __init__(self):
        self._lock = threading.Lock()
        self._checks = {}
        self._ready = False

    def set_check(self, name: str, ok: bool, detail: str = ""):
        with self._lock:
            self._checks[name] = {"status": "ok" if ok else "fail", "detail": detail}

    def set_ready(self, ready: bool):
        with self._lock:
            self._ready = ready

    def snapshot(self):
        with self._lock:
            return dict(self._checks), self._ready


def _make_handler(state: HealthState, service_name: str):
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status_code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                # Liveness: process is up and serving. Never fails once bound.
                self._write_json(200, {"status": "healthy", "service": service_name})
            elif self.path == "/ready":
                checks, ready = state.snapshot()
                overall = "healthy" if ready and all(c["status"] == "ok" for c in checks.values()) else "unhealthy"
                code = 200 if overall == "healthy" else 503
                self._write_json(code, {"status": overall, "checks": checks})
            else:
                self._write_json(404, {"error": "not found"})

        def log_message(self, format, *args):
            # Suppress BaseHTTPRequestHandler's default stderr access logs;
            # health-check polling every few seconds is noise, not a
            # business event worth INFO-level structured logging.
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
