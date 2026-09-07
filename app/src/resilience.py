"""
resilience.py - Circuit breaker + health-state tracking for IoTDB connections.

Wraps IoTDB writes so that once the connection is judged unhealthy (N
consecutive failures), the consumer stops hammering it for
`reset_timeout_s` seconds (fail fast) instead of retrying every batch and
piling up latency, then makes one "half-open" trial call to see if it has
recovered.
"""

import logging
import threading
import time

log = logging.getLogger("resilience")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    """
    Standard 3-state circuit breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    - CLOSED: calls pass through; failures increment a counter.
    - OPEN: calls are rejected immediately until reset_timeout_s elapses.
    - HALF_OPEN: one trial call is allowed through; success -> CLOSED,
      failure -> OPEN again (with the timeout restarted).
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout_s: float = 30.0, name: str = "circuit"):
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self.name = name
        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            return self._resolve_state()

    def _resolve_state(self) -> str:
        if self._state == "OPEN" and (time.time() - self._opened_at) >= self.reset_timeout_s:
            self._state = "HALF_OPEN"
            log.warning("Circuit '%s' transitioning OPEN -> HALF_OPEN (trial call allowed)", self.name)
        return self._state

    def call(self, func, *args, **kwargs):
        with self._lock:
            state = self._resolve_state()
            if state == "OPEN":
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN, rejecting call without attempting it"
                )

        try:
            result = func(*args, **kwargs)
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    def _record_success(self):
        with self._lock:
            if self._state != "CLOSED":
                log.info("Circuit '%s' recovered -> CLOSED", self.name)
            self._state = "CLOSED"
            self._failure_count = 0

    def _record_failure(self):
        with self._lock:
            self._failure_count += 1
            if self._state == "HALF_OPEN" or self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()
                log.error(
                    "Circuit '%s' OPEN after %d consecutive failures (cooling down %.0fs)",
                    self.name, self._failure_count, self.reset_timeout_s,
                )
