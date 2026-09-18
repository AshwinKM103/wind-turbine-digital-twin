"""HTTP client and session management with retry backoff and error mapping.

Provides thread-safe JWT authentication token management, automatic token refreshing,
exponential jittered retry backoff on transient errors (429, 502, 503, 504), and paginated
REST resource traversal.

Exported Classes:
    ThingsboardSession: Thread-safe JWT token and credential state holder.
    ThingsboardHttpClient: Resilient HTTP client wrapper around standard library urllib.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.tools.thingsboard_core.exceptions import ThingsboardAPIError, ThingsboardAuthError

logger = logging.getLogger("tb_core.http_client")


class ThingsboardSession:
    """Manages JWT authentication token with thread-safe auto-refresh.

    Attributes:
        base_url: Base HTTP URL of the ThingsBoard server.
        timeout_s: Socket timeout for HTTP requests in seconds.
    """

    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        """Initializes the ThingsboardSession.

        Args:
            base_url: Root endpoint URL of the ThingsBoard service.
            timeout_s: Socket timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._lock = threading.Lock()

    def login(self, username: str, password: str) -> str:
        """Executes POST /api/auth/login and stores JWT and refresh token.

        Args:
            username: User account email or identifier.
            password: Plaintext account password.

        Returns:
            Extracted JWT bearer token string.

        Raises:
            ThingsboardAuthError: If authentication credentials are invalid or login fails.
        """
        url = f"{self.base_url}/api/auth/login"
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                with self._lock:
                    self._token = data.get("token")
                    self._refresh_token = data.get("refreshToken")
                    self._username = username
                    self._password = password
                if not self._token:
                    raise ThingsboardAuthError("Login response missing token")
                return self._token
        except urllib.error.HTTPError as e:
            raise ThingsboardAuthError(f"Login failed for {username}: HTTP {e.code}") from e
        except Exception as e:
            raise ThingsboardAuthError(f"Login connection failed for {username}: {e}") from e

    def set_token(self, token: str) -> None:
        """Explicitly sets an auth token (e.g. for impersonation or pre-shared tokens).

        Args:
            token: Raw JWT token string.
        """
        with self._lock:
            self._token = token

    def refresh(self) -> str:
        """Refreshes the active token using refresh token or stored login credentials.

        Returns:
            Fresh JWT bearer token string.

        Raises:
            ThingsboardAuthError: If neither refresh token nor stored credentials succeed.
        """
        with self._lock:
            refresh_tok = self._refresh_token
            user = self._username
            pwd = self._password

        if refresh_tok:
            url = f"{self.base_url}/api/auth/token"
            payload = json.dumps({"refreshToken": refresh_tok}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    new_token = data.get("token")
                    if new_token:
                        with self._lock:
                            self._token = new_token
                            self._refresh_token = data.get("refreshToken", refresh_tok)
                        return new_token
            except Exception as e:
                logger.warning(f"Token refresh with refreshToken failed: {e}")

        if user and pwd:
            return self.login(user, pwd)

        raise ThingsboardAuthError("No credentials or refresh token available to refresh session")

    def get_token(self) -> str:
        """Returns valid JWT token, refreshing if necessary.

        Returns:
            Active JWT bearer token string.
        """
        with self._lock:
            token = self._token
        if not token:
            return self.refresh()
        return token

    @property
    def auth_headers(self) -> dict[str, str]:
        """Dictionary of HTTP headers including Bearer authorization and content negotiation."""
        tok = self.get_token()
        return {
            "Authorization": f"Bearer {tok}",
            "X-Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


class ThingsboardHttpClient:
    """HTTP client with standard JSON encode/decode, retry backoff, and error mapping.

    Attributes:
        session: Active ThingsboardSession instance.
        max_retries: Maximum number of retry attempts for transient errors.
        retry_backoff: Exponential backoff factor.
    """

    def __init__(
        self,
        session: ThingsboardSession,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ) -> None:
        """Initializes the HTTP client.

        Args:
            session: Active ThingsboardSession instance providing authentication headers.
            max_retries: Maximum retry attempts for transient network or rate-limiting errors.
            retry_backoff: Multiplier base for exponential backoff delay calculation.
        """
        self.session = session
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def request(
        self,
        method: str,
        path: str,
        data: Any = None,
        params: Optional[dict[str, Any]] = None,
        retries: Optional[int] = None,
    ) -> Any:
        """Dispatches an HTTP request with automatic retry, backoff, and 401 token refresh.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.).
            path: Relative URI endpoint (e.g. '/api/device').
            data: Optional payload object (serialized to JSON) or raw bytes.
            params: Optional query string parameters dictionary.
            retries: Optional override for max retry attempts.

        Returns:
            Parsed JSON response (dict or list), string, or None if response body is empty.

        Raises:
            ThingsboardAPIError: When the server returns an unhandled HTTP error code.
        """
        base = self.session.base_url.rstrip("/")
        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{base}{clean_path}"
        if params:
            query = urllib.parse.urlencode(params)
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{query}"

        max_attempts = (retries if retries is not None else self.max_retries) + 1
        payload_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                payload_bytes = json.dumps(data).encode("utf-8")
            elif isinstance(data, bytes):
                payload_bytes = data
            elif isinstance(data, str):
                payload_bytes = data.encode("utf-8")

        for attempt in range(1, max_attempts + 1):
            headers = self.session.auth_headers
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers=headers,
                method=method.upper(),
            )
            try:
                with urllib.request.urlopen(req, timeout=self.session.timeout_s) as resp:
                    resp_bytes = resp.read()
                    if not resp_bytes:
                        return None
                    try:
                        return json.loads(resp_bytes.decode("utf-8"))
                    except json.JSONDecodeError:
                        return resp_bytes.decode("utf-8")

            except urllib.error.HTTPError as e:
                resp_text = ""
                try:
                    resp_text = e.read().decode("utf-8")
                except Exception:
                    pass

                # Handle 401 token refresh
                if e.code == 401 and path != "/api/auth/login" and attempt < max_attempts:
                    logger.warning("HTTP 401 received; refreshing token...")
                    try:
                        self.session.refresh()
                        continue
                    except ThingsboardAuthError:
                        raise ThingsboardAPIError("Token expired and refresh failed", 401, resp_text)

                # Retry on transient codes: 429, 502, 503, 504
                if e.code in (429, 502, 503, 504) and attempt < max_attempts:
                    wait_time = (self.retry_backoff ** attempt) + random.uniform(0.1, 0.4)
                    logger.warning(f"HTTP {e.code} on attempt {attempt}/{max_attempts}. Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

                raise ThingsboardAPIError(f"API request failed: {method.upper()} {clean_path}", e.code, resp_text)

            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_attempts:
                    wait_time = (self.retry_backoff ** attempt) + random.uniform(0.1, 0.4)
                    logger.warning(f"Connection error ({e}) on attempt {attempt}/{max_attempts}. Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
                raise ThingsboardAPIError(f"Network error on {method.upper()} {clean_path}: {e}", 0, str(e))

        raise ThingsboardAPIError(f"Request failed after {max_attempts} attempts", 500)

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Issues an HTTP GET request.

        Args:
            path: Relative API endpoint path.
            params: Optional query parameters.

        Returns:
            Parsed JSON or text response.
        """
        return self.request("GET", path, params=params)

    def post(self, path: str, data: Any = None, params: Optional[dict[str, Any]] = None) -> Any:
        """Issues an HTTP POST request.

        Args:
            path: Relative API endpoint path.
            data: Payload object or byte buffer.
            params: Optional query parameters.

        Returns:
            Parsed JSON or text response.
        """
        return self.request("POST", path, data=data, params=params)

    def delete(self, path: str, params: Optional[dict[str, Any]] = None) -> bool:
        """Issues an HTTP DELETE request.

        Args:
            path: Relative API endpoint path.
            params: Optional query parameters.

        Returns:
            True if deletion succeeded, False if API call failed.
        """
        try:
            self.request("DELETE", path, params=params)
            return True
        except ThingsboardAPIError:
            return False

    def paginated_get(
        self,
        path: str,
        page_size: int = 100,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Traverses paginated ThingsBoard endpoints until all pages are retrieved.

        Args:
            path: Relative API endpoint path.
            page_size: Number of records to request per page.
            extra_params: Additional query parameters to include.

        Returns:
            Combined list of item dictionaries across all pages.
        """
        items: list[dict[str, Any]] = []
        page = 0
        params = dict(extra_params or {})
        params["pageSize"] = page_size

        while True:
            params["page"] = page
            res = self.get(path, params=params)
            if isinstance(res, list):
                items.extend(res)
                break
            if isinstance(res, dict):
                data = res.get("data", [])
                if isinstance(data, list):
                    items.extend(data)
                    total_pages = res.get("totalPages", 1)
                    if page + 1 >= total_pages or not res.get("hasNext", False):
                        break
                    page += 1
                else:
                    break
            else:
                break
        return items
