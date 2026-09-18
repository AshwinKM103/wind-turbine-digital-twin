"""
Circuit breaker pattern for fault isolation and resilience.

Provides a thread-safe three-state circuit breaker (CLOSED, OPEN, HALF_OPEN)
guarding external service calls against cascading failures.

The implementation supports:

    - Configurable failure threshold and reset cooldown
    - Thread-safe state transitions and trial call execution
    - Automatic recovery upon successful operations

Key classes / functions:

    - CircuitBreakerOpenError: Exception raised when call is rejected by open breaker.
    - CircuitBreaker: Circuit breaker state machine and execution guard.

"""

import logging
import threading
import time

log = logging.getLogger("resilience")


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    """
    Three-state circuit breaker (CLOSED, OPEN, HALF_OPEN) for fault isolation.

    Monitors consecutive operation failures and trips to OPEN state to prevent
    repeated load on failing downstream services. Recovers through HALF_OPEN
    trial operations after a cooldown period.

    Args:
        failure_threshold (int, optional): Number of consecutive failures before opening. Defaults to 5.
        reset_timeout_s (float, optional): Seconds to wait before attempting recovery trial. Defaults to 30.0.
        name (str, optional): Descriptive name for logging. Defaults to 'circuit'.

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
        """
        Return the current operational state of the circuit breaker.

        Returns:
            str: One of 'CLOSED', 'OPEN', or 'HALF_OPEN'.

        """
        with self._lock:
            return self._resolve_state()

    def _resolve_state(self) -> str:
        if self._state == "OPEN" and (time.time() - self._opened_at) >= self.reset_timeout_s:
            self._state = "HALF_OPEN"
            log.warning("Circuit '%s' transitioning OPEN -> HALF_OPEN (trial call allowed)", self.name)
        return self._state

    def call(self, func, *args, **kwargs):
        """
        Execute callable within circuit breaker guard.

        Args:
            func (Callable): Function to execute.
            *args: Positional arguments forwarded to func.
            **kwargs: Keyword arguments forwarded to func.

        Returns:
            Any: Return value of func.

        Raises:
            CircuitBreakerOpenError: If the circuit is OPEN and calls are rejected.
            Exception: Any exception raised by func if the call fails.

        Example:
            >>> breaker = CircuitBreaker(failure_threshold=3)
            >>> result = breaker.call(lambda x: x * 2, 5)
            >>> print(result)
            10

        """
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

