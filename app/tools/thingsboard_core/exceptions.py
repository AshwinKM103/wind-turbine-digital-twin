"""Custom exceptions for ThingsBoard client and management operations.

Defines the hierarchy of exceptions raised during ThingsBoard authentication,
session handling, and REST API communication.

Exported Classes:
    ThingsboardError: Base exception for all ThingsBoard operations.
    ThingsboardAuthError: Raised on 401 Unauthorized or credential failures.
    ThingsboardAPIError: Raised on HTTP 4xx/5xx responses from the server.
"""

from __future__ import annotations


class ThingsboardError(Exception):
    """Base exception for all ThingsBoard operations."""
    pass


class ThingsboardAuthError(ThingsboardError):
    """Raised when authentication fails (HTTP 401 or invalid credentials)."""
    pass


class ThingsboardAPIError(ThingsboardError):
    """Raised when REST API returns an HTTP 4xx or 5xx error."""

    def __init__(self, message: str, status_code: int = 500, response_text: str = "") -> None:
        """Initializes ThingsboardAPIError with HTTP status code and response payload.

        Args:
            message: High-level error description.
            status_code: HTTP status code returned by the server.
            response_text: Raw error response body text.
        """
        super().__init__(f"{message} (HTTP {status_code}): {response_text}")
        self.status_code = status_code
        self.response_text = response_text

