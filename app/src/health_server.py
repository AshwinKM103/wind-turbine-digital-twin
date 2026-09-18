"""
Health and readiness HTTP probe server.

Provides minimal, non-blocking /health (liveness) and /ready (readiness)
endpoints running on a dedicated daemon background thread for container
healthchecks.

The implementation supports:

    - Lightweight HTTP server on a configurable port
    - Thread-safe state recording and snapshot inspection
    - Liveness (/health) and multi-component readiness (/ready) checks

Key classes / functions:

    - HealthState: Thread-safe mutable status container.
    - start_health_server: Launch background HTTP server and return state handle.

"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("health")


class HealthState:
    """
    Thread-safe mutable status container shared across application threads.

    Maintains component health checks and readiness flags, synchronizing access
    with a reentrant-safe mutex.

    """

    def __init__(self):
        self._lock = threading.Lock()
        self._checks = {}
        self._ready = False

    def set_check(self, name: str, ok: bool, detail: str = ""):
        """
        Record the health status of a named subsystem or dependency.

        Args:
            name (str): Identifier of the component or check (e.g. 'kafka', 'iotdb').
            ok (bool): True if healthy, False otherwise.
            detail (str, optional): Additional diagnostic context. Defaults to "".

        """
        with self._lock:
            self._checks[name] = {"status": "ok" if ok else "fail", "detail": detail}

    def set_ready(self, ready: bool):
        """
        Set overall application readiness state.

        Args:
            ready (bool): True if ready to accept traffic, False otherwise.

        """
        with self._lock:
            self._ready = ready

    def snapshot(self):
        """
        Return an atomic snapshot of registered checks and overall readiness.

        Returns:
            tuple[dict, bool]: A copy of current checks dictionary and readiness flag.

        """
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
                self._write_json(200, {"status": "healthy", "service": service_name})
            elif self.path == "/ready":
                checks, ready = state.snapshot()
                overall = "healthy" if ready and all(c["status"] == "ok" for c in checks.values()) else "unhealthy"
                code = 200 if overall == "healthy" else 503
                self._write_json(code, {"status": overall, "checks": checks})
            else:
                self._write_json(404, {"error": "not found"})

        def log_message(self, format, *args):
            pass

    return Handler


def start_health_server(port: int, service_name: str) -> HealthState:
    """
    Start the health server in a daemon thread and return its state container.

    Args:
        port (int): TCP port number on which to bind the HTTP server.
        service_name (str): Identifying name of the service returned in /health responses.

    Returns:
        HealthState: Mutable handle used to publish health and readiness status.

    Example:
        >>> state = start_health_server(8080, "my-service")
        >>> state.set_ready(True)

    """
    state = HealthState()
    handler_cls = _make_handler(state, service_name)
    server = HTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    log.info("Health server listening on :%d (/health, /ready)", port)
    return state

