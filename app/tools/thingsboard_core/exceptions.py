"""Exceptions for ThingsBoard operations."""

from __future__ import annotations


class ThingsboardError(Exception):
    """Base exception for all ThingsBoard operations."""
    pass


class ThingsboardAuthError(ThingsboardError):
    """Raised when authentication fails (HTTP 401 or invalid credentials)."""
    pass


class ThingsboardAPIError(ThingsboardError):
    """Raised when REST API returns an HTTP 4xx or 5xx error."""

    def __init__(self, message: str, status_code: int = 500, response_text: str = ""):
        super().__init__(f"{message} (HTTP {status_code}): {response_text}")
        self.status_code = status_code
        self.response_text = response_text
