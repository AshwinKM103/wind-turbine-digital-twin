"""Unit tests for the circuit breaker used to protect IoTDB writes."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from resilience import CircuitBreaker, CircuitBreakerOpenError  # noqa: E402


def failing_call():
    raise RuntimeError("simulated downstream failure")


def succeeding_call():
    return "ok"


class TestCircuitBreaker:
    def test_starts_closed_and_allows_calls(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=1.0)
        assert cb.state == "CLOSED"
        assert cb.call(succeeding_call) == "ok"

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=1.0)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(failing_call)
        assert cb.state == "OPEN"

    def test_rejects_calls_while_open(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=10.0)
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        assert cb.state == "OPEN"
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(succeeding_call)

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.05)
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        assert cb.state == "OPEN"
        time.sleep(0.1)
        assert cb.state == "HALF_OPEN"

    def test_recovers_to_closed_on_successful_half_open_call(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.05)
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        time.sleep(0.1)
        assert cb.call(succeeding_call) == "ok"
        assert cb.state == "CLOSED"

    def test_reopens_on_failed_half_open_call(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_s=0.05)
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        time.sleep(0.1)
        assert cb.state == "HALF_OPEN"
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        assert cb.state == "OPEN"

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=1.0)
        with pytest.raises(RuntimeError):
            cb.call(failing_call)
        cb.call(succeeding_call)
        # two more failures should not open it (count was reset)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(failing_call)
        assert cb.state == "CLOSED"
