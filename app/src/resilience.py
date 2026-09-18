"""Circuit breaker and health tracking for external service connections."""

import logging
import threading
import time

log = logging.getLogger("resilience")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    """Three-state circuit breaker (CLOSED, OPEN, HALF_OPEN) for fault isolation."""


    def __init__(self, failure_threshold: int = 5, reset_timeout_s: float = 30.0, name: str = "circuit"):
        """Initialize breaker with failure count threshold and cooldown timeout."""
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self.name = name
        self._lock = threading.Lock()
        self._state = "CLOSED"
        self._failure_count = 0
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        """Current operational state of the circuit breaker."""
        with self._lock:
            return self._resolve_state()

    def _resolve_state(self) -> str:
        """Evaluate and transition OPEN state to HALF_OPEN after timeout."""
        if self._state == "OPEN" and (time.time() - self._opened_at) >= self.reset_timeout_s:
            self._state = "HALF_OPEN"
            log.warning("Circuit '%s' transitioning OPEN -> HALF_OPEN (trial call allowed)", self.name)
        return self._state

    def call(self, func, *args, **kwargs):
        """Execute func within breaker guard, raising CircuitBreakerOpenError if OPEN."""
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
        """Record a successful operation and transition to CLOSED."""
        with self._lock:
            if self._state != "CLOSED":
                log.info("Circuit '%s' recovered -> CLOSED", self.name)
            self._state = "CLOSED"
            self._failure_count = 0

    def _record_failure(self):
        """Record an operation failure and transition to OPEN if threshold exceeded."""
        with self._lock:
            self._failure_count += 1
            if self._state == "HALF_OPEN" or self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()
                log.error(
                    "Circuit '%s' OPEN after %d consecutive failures (cooling down %.0fs)",
                    self.name, self._failure_count, self.reset_timeout_s,
                )
