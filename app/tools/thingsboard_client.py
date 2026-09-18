"""
Hardened ThingsBoard REST API client, entity provisioner, and post-provisioning validator.

Provides a robust HTTP client with exponential backoff, Bearer authentication token management,
impersonation workflows, entity provisioning (tenants, users, devices, dashboards, datasources),
and end-to-end post-provisioning validation routines.

The implementation supports:

    - Resilient REST request handling with exponential jittered retries
    - Automated token refresh and tenant-scoped impersonation contexts
    - Idempotent provisioning of tenants, tenant-admin users, MQTT devices, and dashboards
    - Comprehensive post-provisioning assertion test suite

Key classes / functions:

    - ThingsboardConfig: Connection credentials and timeout configuration dataclass.
    - ThingsboardClient: Core HTTP client executing authenticated API interactions.
    - ThingsboardValidator: Read-only validation harness verifying multi-tenant topology.
    - resolve_secret: Secret resolution utility supporting AWS Secrets Manager and disk files.

"""

from __future__ import annotations

import json
import logging
import os
import random
import secrets
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urljoin

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger("tb_client")


def resolve_secret(
    secret_key: str,
    secrets_file: Optional[str] = None,
    env_vars: Optional[list[str]] = None,
    default: str = "",
) -> str:
    """
    Resolve secret from AWS Secrets Manager, local secrets file, or environment variables.

    Evaluates resolution sources in priority order: AWS Secrets Manager, local filesystem
    credential files, environment variables, and finally default fallback.

    Args:
        secret_key (str): Key name of secret to resolve.
        secrets_file (Optional[str], optional): Explicit path to JSON secrets file. Defaults to None.
        env_vars (Optional[list[str]], optional): Candidate environment variable names. Defaults to None.
        default (str, optional): Default value if secret cannot be found. Defaults to "".

    Returns:
        str: Resolved secret string value.

    """
    aws_secret_name = os.environ.get("AWS_SECRET_NAME") or os.environ.get("TB_AWS_SECRET_NAME")
    if aws_secret_name:
        try:
            import boto3
            client = boto3.client("secretsmanager")
            res = client.get_secret_value(SecretId=aws_secret_name)
            if "SecretString" in res:
                parsed = json.loads(res["SecretString"])
                if isinstance(parsed, dict) and secret_key in parsed:
                    return parsed[secret_key]
                elif isinstance(parsed, str):
                    return parsed
        except Exception as e:
            logger.warning(f"Failed to load secret '{secret_key}' from AWS Secrets Manager: {e}")

    candidate_files = []
    if secrets_file:
        candidate_files.append(Path(secrets_file))
    env_file = os.environ.get("TB_SECRETS_FILE")
    if env_file:
        candidate_files.append(Path(env_file))
    candidate_files.extend([
        Path(".secrets/tb_secrets.json"),
        Path(".secrets/tb_password"),
        Path("app/config/tb-secrets.json"),
    ])

    for fpath in candidate_files:
        if fpath.exists() and fpath.is_file():
            try:
                content = fpath.read_text().strip()
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and secret_key in data:
                        return str(data[secret_key])
                except json.JSONDecodeError:
                    if fpath.name.endswith("password"):
                        return content
            except Exception as e:
                logger.warning(f"Could not read secrets file {fpath}: {e}")

    if env_vars:
        for var in env_vars:
            val = os.environ.get(var)
            if val:
                return val

    return default


@dataclass
class ThingsboardConfig:
    """
    Configuration parameters for connecting to ThingsBoard REST API.

    Attributes:
        host (str): Hostname or IP address of ThingsBoard service.
        port (int): Port number of ThingsBoard service.
        admin_email (str): System administrator username or email.
        admin_password (str): Administrator account password.
        use_tls (bool): Flag indicating if HTTPS should be used.
        verify_tls (bool): Flag indicating whether TLS certificates should be verified.
        ca_cert (Optional[str]): Path to custom CA bundle file.
        max_retries (int): Maximum HTTP retry attempts on transient network errors.
        retry_backoff (float): Exponential backoff multiplier base.
        base_url (str): Derived base URL string.
        token (str): Active JWT Bearer authentication token.

    """

    host: str = "thingsboard"
    port: int = 8080
    admin_email: str = "admin@thingsboard.io"
    admin_password: str = ""
    use_tls: bool = False
    verify_tls: bool = True
    ca_cert: Optional[str] = None
    max_retries: int = 3
    retry_backoff: float = 1.5
    base_url: str = ""
    token: str = ""

    def __post_init__(self) -> None:
        """Construct base_url if not provided."""
        if not self.base_url:
            scheme = "https" if self.use_tls else "http"
            self.base_url = f"{scheme}://{self.host}:{self.port}"


class ThingsboardClient:
    """
    Production-hardened ThingsBoard REST API Client with idempotency and retry logic.

    Attributes:
        config (ThingsboardConfig): Active configuration settings.
        session (requests.Session): HTTP request session.

    """

    def __init__(self, config: ThingsboardConfig) -> None:
        """
        Initialize HTTP session, default headers, and TLS configuration.

        Args:
            config (ThingsboardConfig): Connection configuration options.

        """
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if self.config.ca_cert:
            self.session.verify = self.config.ca_cert
        elif not self.config.verify_tls:
            self.session.verify = False

    def _auth_headers(self) -> dict[str, str]:
        """
        Build authorization headers using current Bearer token.

        Returns:
            dict[str, str]: Authorization headers dictionary.

        """
        if not self.config.token:
            return {}
        return {
            "Authorization": f"Bearer {self.config.token}",
            "X-Authorization": f"Bearer {self.config.token}",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        retries: Optional[int] = None,
        **kwargs,
    ) -> requests.Response:
        """
        Make HTTP request with exponential backoff on retryable errors.

        Args:
            method (str): HTTP verb (e.g. 'GET', 'POST', 'DELETE').
            endpoint (str): API path or relative endpoint URL.
            retries (Optional[int], optional): Maximum retry count. Defaults to None.
            **kwargs: Extra parameters passed to requests.Session.request.

        Returns:
            requests.Response: HTTP response object.

        Raises:
            requests.exceptions.RequestException: On terminal network or timeout error.
            RuntimeError: If retry loop exhausts without returning a response.

        """
        base = self.config.base_url.rstrip("/")
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{base}{path}"

        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())

        max_attempts = (retries if retries is not None else self.config.max_retries) + 1
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=kwargs.pop("timeout", 15),
                    **kwargs,
                )

                # Retry on 429, 502, 503, 504
                if response.status_code in (429, 502, 503, 504) and attempt < max_attempts:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_time = float(retry_after)
                    else:
                        wait_time = (self.config.retry_backoff ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Attempt {attempt}/{max_attempts}: Received HTTP {response.status_code}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    continue

                # Auto-recovery for expired token on 401
                if response.status_code == 401 and endpoint != "/api/auth/login" and attempt < max_attempts:
                    logger.warning("Received 401 Unauthorized. Attempting token refresh / re-authentication...")
                    if self.authenticate():
                        headers.update(self._auth_headers())
                        continue

                return response

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_exception = e
                if attempt < max_attempts:
                    wait_time = (self.config.retry_backoff ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"Attempt {attempt}/{max_attempts}: Connection/timeout issue ({e}). "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                else:
                    raise

        if last_exception:
            raise last_exception
        raise RuntimeError(f"Request failed after {max_attempts} attempts")

    def authenticate(self) -> bool:
        """
        Authenticate with Thingsboard admin credentials.

        Returns:
            bool: True if authentication succeeded and token was assigned, False otherwise.

        """
        logger.info(f"Connecting to Thingsboard at {self.config.base_url}...")
        try:
            response = self._request(
                "POST",
                "/api/auth/login",
                retries=self.config.max_retries,
                json={
                    "username": self.config.admin_email,
                    "password": self.config.admin_password,
                },
            )
            if response.status_code in (200, 201):
                data = response.json()
                self.config.token = data.get("token", "")
                logger.info("✓ Authenticated with Thingsboard")
                return True
            elif response.status_code == 401:
                logger.error("❌ Unauthorized. Check Thingsboard admin credentials.")
                return False
            else:
                logger.error(f"❌ Login failed: {response.status_code} {response.reason}")
                return False
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False

    def get_user_activation_link(self, user_id: str) -> Optional[str]:
        """
        Fetch the one-time activation link for a pending user under sys-admin context.

        Args:
            user_id (str): ThingsBoard user ID UUID.

        Returns:
            Optional[str]: Activation URL string if obtainable, else None.

        """
        try:
            resp = self._request(
                "GET",
                f"/api/user/{user_id}/activationLink",
                headers={"Accept": "text/plain"},
            )
            if resp.status_code in (200, 201):
                text = resp.text.strip()
                return text.strip('"') if text else None
            logger.warning(
                f"Could not fetch activation link for user {user_id}: "
                f"HTTP {resp.status_code} {resp.text}"
            )
        except Exception as e:
            logger.error(f"Error fetching activation link for user {user_id}: {e}")
        return None

    def activate_user(self, user_id: str, password: str) -> bool:
        """
        Activate a pending user with a chosen password without sending an email.

        Args:
            user_id (str): User entity UUID.
            password (str): Desired password to set.

        Returns:
            bool: True on successful activation, False otherwise.

        """
        link = self.get_user_activation_link(user_id)
        if not link:
            logger.error(f"❌ Could not obtain activation link for user {user_id}")
            return False

        token = None
        if "activateToken=" in link:
            token = link.split("activateToken=", 1)[1].split("&", 1)[0]
        if not token:
            logger.error(f"❌ Activation link for user {user_id} had no activateToken: {link}")
            return False

        try:
            resp = self._request(
                "POST",
                "/api/noauth/activate",
                json={
                    "activateToken": token,
                    "password": password,
                    "sendActivationMail": False,
                },
            )
            if resp.status_code in (200, 201):
                logger.info(f"✓ Activated user {user_id}")
                return True
            logger.error(f"❌ Failed to activate user {user_id}: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            logger.error(f"❌ Exception activating user {user_id}: {e}")
            return False

    def login_as_user(self, email: str, password: str) -> Optional[str]:
        """
        Log in as a specific user and return an auth token scoped to that user's tenant.

        Args:
            email (str): Target user email address.
            password (str): Target user password.

        Returns:
            Optional[str]: Scoped Bearer token string if authenticated, else None.

        """
        try:
            resp = self._request(
                "POST",
                "/api/auth/login",
                json={"username": email, "password": password},
            )
            if resp.status_code in (200, 201):
                token = resp.json().get("token")
                if token:
                    logger.info(f"✓ Logged in as '{email}'")
                    return token
            logger.error(f"❌ Login as '{email}' failed: {resp.status_code} {resp.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Exception logging in as '{email}': {e}")
            return None

    def change_password(self, current_password: str, new_password: str) -> bool:
        """
        Change the password of the currently authenticated session user.

        Args:
            current_password (str): Current active password.
            new_password (str): New password to configure.

        Returns:
            bool: True if password was updated, False otherwise.

        """
        try:
            resp = self._request(
                "POST",
                "/api/auth/changePassword",
                json={"currentPassword": current_password, "newPassword": new_password},
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.error(f"❌ Exception changing password: {e}")
            return False

    def logout(self) -> None:
        """
        Invalidate the current session token and clear local credentials.

        """
        if not self.config.token:
            return
        try:
            self._request("POST", "/api/auth/logout")
        except Exception as e:
            logger.warning(f"Logout call failed (token cleared locally anyway): {e}")
        finally:
            self.config.token = ""

    @contextmanager
    def impersonate(self, token: str) -> Iterator[None]:
        """
        Context manager temporarily swapping in a scoped auth token.

        Args:
            token (str): Temporary Bearer token to activate during context block.

        Yields:
            Iterator[None]: Yields control within the temporary token scope.

        """
        previous = self.config.token
        self.config.token = token
        try:
            yield
        finally:
            self.config.token = previous

    def _get_paginated(self, endpoint: str, page_size: int = 100) -> list[dict]:
        """
        Fetch all entity pages from a paginated ThingsBoard REST API endpoint.

        Args:
            endpoint (str): Target REST endpoint path.
            page_size (int, optional): Number of items per page. Defaults to 100.

        Returns:
            list[dict]: Consolidated list of all retrieved entity records across all pages.

        """
        items: list[dict] = []
        page = 0
        delimiter = "&" if "?" in endpoint else "?"

        while True:
            url = f"{endpoint}{delimiter}pageSize={page_size}&page={page}"
            try:
                resp = self._request("GET", url)
                if resp.status_code not in (200, 201):
                    logger.warning(f"Failed to fetch paginated {url}: HTTP {resp.status_code}")
                    break

                body = resp.json()
                if isinstance(body, list):
                    items.extend(body)
                    break
                elif isinstance(body, dict):
                    page_data = body.get("data", [])
                    if isinstance(page_data, list):
                        items.extend(page_data)
                    else:
                        break

                    # Check pagination completion conditions:
                    if "hasNext" in body:
                        if not body["hasNext"]:
                            break
                    elif "totalPages" in body:
                        if page + 1 >= body["totalPages"]:
                            break
                    elif len(page_data) < page_size:
                        break

                    if not page_data:
                        break
                else:
                    break

                page += 1
            except Exception as e:
                logger.error(f"Error fetching paginated data from {endpoint}: {e}")
                break

        return items

    # --- Tenant Management ---
    def list_tenants(self, page_size: int = 100) -> list[dict]:
        """
        List all tenants with pagination.

        Args:
            page_size (int, optional): Page batch size. Defaults to 100.

        Returns:
            list[dict]: List of tenant entity records.

        """
        return self._get_paginated("/api/tenants", page_size=page_size)

    def find_tenant_by_name(self, name: str) -> Optional[dict]:
        """
        Find tenant entity by title name.

        Args:
            name (str): Tenant title to match.

        Returns:
            Optional[dict]: Matching tenant entity dictionary, or None if not found.

        """
        for tenant in self.list_tenants():
            if tenant.get("title") == name:
                return tenant
        return None

    def delete_tenant(self, tenant_id: str) -> bool:
        """
        Delete tenant by its entity UUID.

        Args:
            tenant_id (str): Tenant identifier UUID.

        Returns:
            bool: True if deletion succeeded, False otherwise.

        """
        try:
            resp = self._request("DELETE", f"/api/tenant/{tenant_id}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"Error deleting tenant {tenant_id}: {e}")
            return False

    def create_tenant(
        self,
        name: str,
        description: str = "",
        force_recreate: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Create tenant entity idempotently.

        Args:
            name (str): Tenant title name.
            description (str, optional): Tenant description text. Defaults to "".
            force_recreate (bool, optional): If True, deletes existing tenant before re-creating. Defaults to False.

        Returns:
            tuple[bool, Optional[str]]: Tuple of (success_boolean, tenant_id_uuid).

        """
        existing = self.find_tenant_by_name(name)
        if existing:
            tid = existing.get("id", {}).get("id")
            if force_recreate:
                logger.info(f"Force recreate: Deleting existing tenant '{name}' (ID: {tid})...")
                self.delete_tenant(tid)
            else:
                logger.info(f"✓ Tenant '{name}' already exists (ID: {tid})")
                return True, tid

        logger.info(f"Creating tenant '{name}'...")
        try:
            resp = self._request(
                "POST",
                "/api/tenant",
                json={
                    "title": name,
                    "description": description or f"Multi-tenant isolation entity for {name}",
                },
            )
            if resp.status_code in (200, 201):
                tid = resp.json().get("id", {}).get("id")
                logger.info(f"✓ Tenant '{name}' created (ID: {tid})")
                return True, tid
            elif resp.status_code in (400, 409):
                existing = self.find_tenant_by_name(name)
                tid = existing.get("id", {}).get("id") if existing else None
                if tid:
                    logger.info(f"✓ Tenant '{name}' already exists (ID: {tid})")
                    return True, tid
                logger.error(f"❌ Error creating tenant: {resp.status_code} {resp.text}")
                return False, None
            else:
                logger.error(f"❌ Error creating tenant: {resp.status_code} {resp.text}")
                return False, None
        except Exception as e:
            logger.error(f"❌ Exception creating tenant: {e}")
            return False, None

    # --- User Management ---
    def list_users(self, page_size: int = 100) -> list[dict]:
        """
        List all user entities visible in current session context.

        Args:
            page_size (int, optional): Page batch size. Defaults to 100.

        Returns:
            list[dict]: List of user entities.

        """
        return self._get_paginated("/api/users", page_size=page_size)

    def find_user_by_email(self, email: str) -> Optional[dict]:
        """
        Find user entity by email address.

        Args:
            email (str): Target email address.

        Returns:
            Optional[dict]: User entity dictionary if found, else None.

        """
        try:
            resp = self._request("GET", f"/api/user?email={email}")
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code == 404:
                pass
        except Exception:
            pass
        for u in self.list_users():
            if u.get("email") == email:
                return u
        return None

    def delete_user(self, user_id: str) -> bool:
        """
        Delete user by entity UUID.

        Args:
            user_id (str): User identifier UUID.

        Returns:
            bool: True if deletion succeeded, False otherwise.

        """
        try:
            resp = self._request("DELETE", f"/api/user/{user_id}")
            return resp.status_code in (200, 202, 204)
        except Exception:
            return False

    def create_user(
        self,
        tenant_id: str,
        email: str,
        authority: str = "TENANT_ADMIN",
        first_name: str = "Admin",
        last_name: str = "User",
        customer_id: Optional[str] = None,
        force_recreate: bool = False,
    ) -> tuple[bool, Optional[str], str]:
        """
        Create user entity idempotently with activation credentials.

        Args:
            tenant_id (str): Owning tenant identifier UUID.
            email (str): User login email.
            authority (str, optional): Role authority level ('TENANT_ADMIN', 'CUSTOMER_USER'). Defaults to "TENANT_ADMIN".
            first_name (str, optional): User first name. Defaults to "Admin".
            last_name (str, optional): User last name. Defaults to "User".
            customer_id (Optional[str], optional): Customer entity UUID if CUSTOMER_USER. Defaults to None.
            force_recreate (bool, optional): Whether to remove existing user first. Defaults to False.

        Returns:
            tuple[bool, Optional[str], str]: Tuple of (success_boolean, user_id_uuid, generated_temp_password).

        """
        temp_pwd = secrets.token_urlsafe(16)
        existing = self.find_user_by_email(email)
        if existing:
            uid = existing.get("id", {}).get("id")
            if force_recreate:
                logger.info(f"Force recreate: Deleting existing user '{email}' (ID: {uid})...")
                self.delete_user(uid)
            else:
                logger.info(f"✓ User '{email}' already exists (ID: {uid})")
                return True, uid, temp_pwd

        logger.info(f"Creating user '{email}' ({authority})...")
        payload = {
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "tenantId": {"id": tenant_id, "entityType": "TENANT"},
            "authority": authority,
        }
        if customer_id and authority == "CUSTOMER_USER":
            payload["customerId"] = {"id": customer_id, "entityType": "CUSTOMER"}

        try:
            resp = self._request(
                "POST",
                # sendActivationMail=false prevents failure when SMTP server is not configured.
                "/api/user?sendActivationMail=false",
                json=payload,
            )
            if resp.status_code in (200, 201):
                uid = resp.json().get("id", {}).get("id")
                logger.info(f"✓ User '{email}' created (ID: {uid})")
                return True, uid, temp_pwd
            elif resp.status_code in (400, 409):
                existing = self.find_user_by_email(email)
                uid = existing.get("id", {}).get("id") if existing else None
                if uid:
                    logger.info(f"✓ User '{email}' already exists (ID: {uid})")
                    return True, uid, temp_pwd
                logger.error(f"❌ Error creating user '{email}': {resp.status_code} {resp.text}")
                return False, None, ""
            else:
                logger.error(f"❌ Error creating user '{email}': {resp.status_code} {resp.text}")
                return False, None, ""
        except Exception as e:
            logger.error(f"❌ Exception creating user '{email}': {e}")
            return False, None, ""

    # --- Datasource Management ---
    def list_datasources(self, page_size: int = 100) -> list[dict]:
        """
        List all configured datasources with pagination.

        Args:
            page_size (int, optional): Page batch size. Defaults to 100.

        Returns:
            list[dict]: List of datasource configuration dictionaries.

        """
        return self._get_paginated("/api/datasources", page_size=page_size)

    def find_datasource_by_name(self, name: str) -> Optional[dict]:
        """
        Find datasource by its configured name.

        Args:
            name (str): Target datasource name.

        Returns:
            Optional[dict]: Datasource dictionary if found, else None.

        """
        for ds in self.list_datasources():
            if ds.get("name") == name:
                return ds
        return None

    def delete_datasource(self, datasource_id: str) -> bool:
        """
        Delete datasource by entity identifier UUID.

        Args:
            datasource_id (str): Datasource identifier UUID.

        Returns:
            bool: True if deletion succeeded, False otherwise.

        """
        try:
            resp = self._request("DELETE", f"/api/datasource/{datasource_id}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"Error deleting datasource {datasource_id}: {e}")
            return False

    def create_datasource(
        self,
        tenant_id: str,
        name: str,
        db_host: str,
        db_port: int,
        db_name: str,
        db_user: str,
        db_password: str,
        force_recreate: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Create PostgreSQL / JDBC datasource for Thingsboard.

        Args:
            tenant_id (str): Owning tenant identifier UUID.
            name (str): Datasource name.
            db_host (str): Database server hostname.
            db_port (int): Database server port number.
            db_name (str): Target database name.
            db_user (str): Database username.
            db_password (str): Database user password.
            force_recreate (bool, optional): Whether to delete existing datasource first. Defaults to False.

        Returns:
            tuple[bool, Optional[str]]: Tuple of (success_boolean, datasource_id_uuid).

        """
        existing = self.find_datasource_by_name(name)
        if existing:
            ds_id = existing.get("id", {}).get("id")
            if force_recreate:
                logger.info(f"Force recreate: Deleting existing datasource '{name}'...")
                self.delete_datasource(ds_id)
            else:
                logger.info(f"✓ Datasource '{name}' already exists (ID: {ds_id})")
                return True, ds_id

        logger.info(f"Creating datasource '{name}'...")
        try:
            resp = self._request(
                "POST",
                "/api/datasource",
                json={
                    "name": name,
                    "type": "postgres",
                    "tenantId": {"id": tenant_id, "entityType": "TENANT"},
                    "configuration": {
                        "jdbcUrl": f"jdbc:postgresql://{db_host}:{db_port}/{db_name}",
                        "username": db_user,
                        "password": db_password,
                        "driverClassName": "org.postgresql.Driver",
                    },
                },
            )
            if resp.status_code in (200, 201):
                ds_id = resp.json().get("id", {}).get("id")
                logger.info(f"✓ Datasource '{name}' created (ID: {ds_id})")
                return True, ds_id
            elif resp.status_code in (400, 409):
                existing = self.find_datasource_by_name(name)
                ds_id = existing.get("id", {}).get("id") if existing else None
                if ds_id:
                    return True, ds_id
                return False, None
            else:
                logger.error(f"❌ Error creating datasource: {resp.status_code} {resp.text}")
                return False, None
        except Exception as e:
            logger.error(f"❌ Exception creating datasource: {e}")
            return False, None

    # --- Device Management ---
    def list_devices(self, page_size: int = 100) -> list[dict]:
        """
        List all devices visible to the current tenant session.

        Args:
            page_size (int, optional): Page batch size. Defaults to 100.

        Returns:
            list[dict]: List of device entity dictionaries.

        """
        return self._get_paginated("/api/tenant/devices", page_size=page_size)

    def find_device_by_name(self, name: str) -> Optional[dict]:
        """
        Find device entity by name.

        Args:
            name (str): Device name to find.

        Returns:
            Optional[dict]: Device dictionary if found, else None.

        """
        for d in self.list_devices():
            if d.get("name") == name:
                return d
        return None

    def delete_device(self, device_id: str) -> bool:
        """
        Delete device entity by identifier UUID.

        Args:
            device_id (str): Device entity UUID.

        Returns:
            bool: True if deleted successfully, False otherwise.

        """
        try:
            resp = self._request("DELETE", f"/api/device/{device_id}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"Error deleting device {device_id}: {e}")
            return False

    def get_device_credentials(self, device_id: str) -> Optional[dict]:
        """
        Fetch credentials object for a given device.

        Args:
            device_id (str): Device entity UUID.

        Returns:
            Optional[dict]: Credentials dictionary containing credentialsId token, or None.

        """
        try:
            resp = self._request("GET", f"/api/device/{device_id}/credentials")
            if resp.status_code in (200, 201):
                return resp.json()
        except Exception:
            pass
        return None

    def get_device_token(self, device_id: str) -> Optional[str]:
        """
        Fetch MQTT access token credential string for a device.

        Args:
            device_id (str): Device entity UUID.

        Returns:
            Optional[str]: MQTT access token string if present, else None.

        """
        creds = self.get_device_credentials(device_id)
        if creds:
            return creds.get("credentialsId")
        return None

    def save_device_attributes(self, device_id: str, attributes: dict, scope: str = "SERVER_SCOPE") -> bool:
        """
        Save attributes for a device in the specified scope.

        Args:
            device_id (str): Device entity UUID.
            attributes (dict): Key-value attribute dictionary.
            scope (str, optional): Attribute scope string. Defaults to "SERVER_SCOPE".

        Returns:
            bool: True if attributes saved successfully, False otherwise.

        """
        try:
            resp = self._request(
                "POST",
                f"/api/plugins/telemetry/DEVICE/{device_id}/{scope}",
                json=attributes,
            )
            return resp.status_code in (200, 201)
        except Exception:
            return False

    def get_device_attributes(self, device_id: str, scope: str = "SERVER_SCOPE") -> dict:
        """
        Fetch attributes for a device in the specified scope.

        Args:
            device_id (str): Device entity UUID.
            scope (str, optional): Attribute scope string. Defaults to "SERVER_SCOPE".

        Returns:
            dict: Key-value dictionary of device attributes.

        """
        try:
            resp = self._request("GET", f"/api/plugins/telemetry/DEVICE/{device_id}/values/attributes/{scope}")
            if resp.status_code in (200, 201):
                data = resp.json()
                if isinstance(data, list):
                    return {item.get("key"): item.get("value") for item in data if "key" in item}
                elif isinstance(data, dict):
                    return data
        except Exception as e:
            logger.error(f"Error getting attributes for device {device_id}: {e}")
        return {}

    def create_device(
        self,
        tenant_id: str,
        device_name: str,
        device_type: str = "turbine",
        attributes: Optional[dict] = None,
        force_recreate: bool = False,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Create MQTT device with telemetry attributes and return credentials.

        Args:
            tenant_id (str): Owning tenant identifier UUID.
            device_name (str): Registered device name.
            device_type (str, optional): Device type label. Defaults to "turbine".
            attributes (Optional[dict], optional): Server attributes to assign. Defaults to None.
            force_recreate (bool, optional): Whether to recreate if exists. Defaults to False.

        Returns:
            tuple[bool, Optional[str], Optional[str]]: Tuple of (success, device_id, access_token).

        """
        existing = self.find_device_by_name(device_name)
        if existing:
            dev_id = existing.get("id", {}).get("id")
            if force_recreate:
                logger.info(f"Force recreate: Deleting existing device '{device_name}'...")
                self.delete_device(dev_id)
            else:
                creds = self.get_device_credentials(dev_id)
                token = creds.get("credentialsId") if creds else None
                if attributes:
                    self.save_device_attributes(dev_id, attributes)
                return True, dev_id, token

        try:
            resp = self._request(
                "POST",
                "/api/device",
                json={
                    "name": device_name,
                    "type": device_type,
                    "tenantId": {"id": tenant_id, "entityType": "TENANT"},
                    "transportType": "MQTT",
                },
            )
            if resp.status_code in (200, 201):
                dev_id = resp.json().get("id", {}).get("id")
                creds = self.get_device_credentials(dev_id)
                token = creds.get("credentialsId") if creds else None
                if attributes:
                    self.save_device_attributes(dev_id, attributes)
                return True, dev_id, token
            elif resp.status_code in (400, 409):
                existing = self.find_device_by_name(device_name)
                dev_id = existing.get("id", {}).get("id") if existing else None
                creds = self.get_device_credentials(dev_id) if dev_id else None
                token = creds.get("credentialsId") if creds else None
                if dev_id and attributes:
                    self.save_device_attributes(dev_id, attributes)
                return True, dev_id, token
            else:
                logger.error(f"❌ Error creating device '{device_name}': {resp.status_code} {resp.text}")
                return False, None, None
        except Exception as e:
            logger.error(f"❌ Exception creating device '{device_name}': {e}")
            return False, None, None

    # --- Dashboard Management ---
    def list_dashboards(self, page_size: int = 100) -> list[dict]:
        """
        List all dashboards visible to the current tenant session with pagination.

        Args:
            page_size (int, optional): Page batch size. Defaults to 100.

        Returns:
            list[dict]: List of dashboard dictionaries.

        """
        return self._get_paginated("/api/dashboards", page_size=page_size)

    def find_dashboard_by_title(self, title: str) -> Optional[dict]:
        """
        Find dashboard entity by title.

        Args:
            title (str): Dashboard title to locate.

        Returns:
            Optional[dict]: Dashboard dictionary if found, else None.

        """
        for d in self.list_dashboards():
            if d.get("title") == title:
                return d
        return None

    def delete_dashboard(self, dashboard_id: str) -> bool:
        """
        Delete dashboard entity by identifier UUID.

        Args:
            dashboard_id (str): Dashboard entity UUID.

        Returns:
            bool: True if deletion succeeded, False otherwise.

        """
        try:
            resp = self._request("DELETE", f"/api/dashboard/{dashboard_id}")
            return resp.status_code in (200, 202, 204)
        except Exception as e:
            logger.error(f"Error deleting dashboard {dashboard_id}: {e}")
            return False

    def create_dashboard(
        self,
        tenant_id: str,
        title: str,
        configuration: Optional[dict] = None,
        description: str = "",
        force_recreate: bool = False,
    ) -> tuple[bool, Optional[str]]:
        """
        Create Thingsboard dashboard idempotently.

        Args:
            tenant_id (str): Owning tenant identifier UUID.
            title (str): Dashboard title string.
            configuration (Optional[dict], optional): Gridster configuration dictionary. Defaults to None.
            description (str, optional): Descriptive text. Defaults to "".
            force_recreate (bool, optional): Whether to delete existing dashboard first. Defaults to False.

        Returns:
            tuple[bool, Optional[str]]: Tuple of (success, dashboard_id).

        """
        existing = self.find_dashboard_by_title(title)
        if existing:
            dash_id = existing.get("id", {}).get("id")
            if force_recreate:
                logger.info(f"Force recreate: Deleting existing dashboard '{title}'...")
                self.delete_dashboard(dash_id)
            else:
                logger.info(f"✓ Dashboard '{title}' already exists (ID: {dash_id})")
                return True, dash_id

        logger.info(f"Creating dashboard '{title}'...")
        payload = {
            "title": title,
            "description": description,
            "configuration": configuration or {
                "gridSettings": {
                    "columns": 24,
                    "margins": [10, 10],
                    "backgroundColor": "rgb(255, 255, 255)",
                }
            },
        }
        try:
            resp = self._request("POST", "/api/dashboard", json=payload)
            if resp.status_code in (200, 201):
                dash_id = resp.json().get("id", {}).get("id")
                logger.info(f"✓ Dashboard '{title}' created (ID: {dash_id})")
                return True, dash_id
            elif resp.status_code in (400, 409):
                existing = self.find_dashboard_by_title(title)
                dash_id = existing.get("id", {}).get("id") if existing else None
                if dash_id:
                    return True, dash_id
                return False, None
            else:
                logger.error(f"❌ Error creating dashboard '{title}': {resp.status_code} {resp.text}")
                return False, None
        except Exception as e:
            logger.error(f"❌ Exception creating dashboard '{title}': {e}")
            return False, None


class ThingsboardValidator:
    """
    Read-only post-provisioning validator verifying entities and configurations.

    Attributes:
        client (ThingsboardClient): Client instance executing REST verification calls.
        checks_passed (int): Cumulative count of successful validation checks.
        checks_failed (int): Cumulative count of failed validation checks.

    """

    def __init__(self, client: ThingsboardClient) -> None:
        """
        Initialize validator with client instance and reset pass/fail tallies.

        Args:
            client (ThingsboardClient): Authenticated Thingsboard client instance.

        """
        self.client = client
        self.checks_passed = 0
        self.checks_failed = 0

    def check_tenant_exists(self, tenant_name: str) -> bool:
        """
        Verify whether a tenant exists by title.

        Args:
            tenant_name (str): Tenant title to locate.

        Returns:
            bool: True if tenant exists, False otherwise.

        """
        logger.info(f"Checking tenant '{tenant_name}'...")
        tenant = self.client.find_tenant_by_name(tenant_name)
        if tenant:
            tid = tenant.get("id", {}).get("id")
            logger.info(f"✓ Tenant '{tenant_name}' exists (ID: {tid})")
            self.checks_passed += 1
            return True
        logger.error(f"❌ Tenant '{tenant_name}' not found")
        self.checks_failed += 1
        return False

    def check_user_exists(self, email: str, role_description: str = "user") -> bool:
        """
        Verify whether a user exists by email address.

        Args:
            email (str): Target email address.
            role_description (str, optional): Role label for log reporting. Defaults to "user".

        Returns:
            bool: True if user exists, False otherwise.

        """
        logger.info(f"Checking {role_description} '{email}'...")
        user = self.client.find_user_by_email(email)
        if user:
            uid = user.get("id", {}).get("id")
            auth = user.get("authority")
            logger.info(f"✓ {role_description.capitalize()} '{email}' exists (ID: {uid}, authority: {auth})")
            self.checks_passed += 1
            return True
        logger.error(f"❌ {role_description.capitalize()} '{email}' not found")
        self.checks_failed += 1
        return False

    def check_tenant_admin_user(self, admin_email: str) -> bool:
        """
        Verify whether the tenant admin user account exists.

        Args:
            admin_email (str): Tenant admin email address.

        Returns:
            bool: True if admin user exists, False otherwise.

        """
        return self.check_user_exists(admin_email, "tenant admin user")

    def check_datasource_health(self, tenant_name: str) -> bool:
        """
        Verify advisory datasource presence for a given tenant.

        Args:
            tenant_name (str): Tenant title name.

        Returns:
            bool: True (advisory check).

        """
        logger.info(f"Checking IoTDB datasource for '{tenant_name}'...")
        ds_name = f"iotdb-{tenant_name}"
        ds = self.client.find_datasource_by_name(ds_name)
        if ds:
            ds_id = ds.get("id", {}).get("id")
            logger.info(f"✓ Datasource '{ds_name}' exists (ID: {ds_id})")
            self.checks_passed += 1
            return True
        logger.warning(f"⚠ Datasource '{ds_name}' not found (optional in Phase 1)")
        self.checks_passed += 1
        return True

    def check_mqtt_devices(self, turbine_identifiers: list[str]) -> bool:
        """
        Verify that all specified MQTT device names exist in ThingsBoard.

        Args:
            turbine_identifiers (list[str]): List of turbine device identifier strings.

        Returns:
            bool: True if all specified devices exist, False otherwise.

        """
        logger.info(f"Checking MQTT devices: {turbine_identifiers}...")
        devices = {d.get("name"): d for d in self.client.list_devices()}
        all_found = True

        for ident in turbine_identifiers:
            found = False
            for dname in devices:
                if ident in dname:
                    found = True
                    break
            if found:
                logger.info(f"✓ Device '{ident}' found in Thingsboard")
            else:
                logger.error(f"❌ Device '{ident}' not found")
                all_found = False

        if all_found:
            self.checks_passed += 1
        else:
            self.checks_failed += 1
        return all_found

    def check_dashboards(self, dashboard_titles: list[str]) -> bool:
        """
        Verify that all specified dashboards exist in ThingsBoard.

        Args:
            dashboard_titles (list[str]): List of dashboard title strings.

        Returns:
            bool: True if all dashboards exist, False otherwise.

        """
        logger.info(f"Checking dashboards: {dashboard_titles}...")
        dashboards = {d.get("title"): d for d in self.client.list_dashboards()}
        all_found = True

        for title in dashboard_titles:
            if title in dashboards:
                logger.info(f"✓ Dashboard '{title}' exists")
            else:
                logger.error(f"❌ Dashboard '{title}' not found")
                all_found = False

        if all_found:
            self.checks_passed += 1
        else:
            self.checks_failed += 1
        return all_found

    def validate_single_tenant(
        self,
        tenant_name: str,
        admin_email: str,
        turbine_ids: list[str],
    ) -> bool:
        """
        Run single tenant validation checks covering tenant, admin user, and devices.

        Args:
            tenant_name (str): Tenant name.
            admin_email (str): Tenant admin email.
            turbine_ids (list[str]): List of turbine device identifiers.

        Returns:
            bool: True if all validation assertions pass, False otherwise.

        """
        self.checks_passed = 0
        self.checks_failed = 0
        checks = [
            self.check_tenant_exists(tenant_name),
            self.check_tenant_admin_user(admin_email),
            self.check_datasource_health(tenant_name),
            self.check_mqtt_devices(turbine_ids),
        ]
        return all(checks)

    def validate_fleet(self, fleet: dict) -> bool:
        """
        Validate multi-tenant provisioning across all customers in fleet configuration.

        Args:
            fleet (dict): Fleet dictionary containing customer topologies.

        Returns:
            bool: True if all customers and resources pass validation, False otherwise.

        """
        self.checks_passed = 0
        self.checks_failed = 0
        all_ok = True

        for customer in fleet.get("customers", []):
            cid = customer["customer_id"]
            admin_email = f"{cid}_admin@example.com"
            ro_email = f"{cid}_user@example.com"
            turbine_ids = []
            for s in customer.get("sites", []):
                for t in s.get("turbines", []):
                    turbine_ids.append(f"{cid}.{s.get('site_id', 'site1')}.{t['turbine_id']}")

            dashboard_titles = [
                f"{customer.get('display_name', cid)} Fleet Overview",
                f"{customer.get('display_name', cid)} Alerts & Breaches",
                f"{customer.get('display_name', cid)} KPI Dashboard",
                f"{customer.get('display_name', cid)} Turbine Comparison",
            ]

            logger.info(f"\n--- Validating Customer: {cid} ---")
            if not self.check_tenant_exists(cid):
                all_ok = False
            if not self.check_tenant_admin_user(admin_email):
                all_ok = False
            if not self.check_user_exists(ro_email, "customer read-only user"):
                all_ok = False
            if not self.check_mqtt_devices(turbine_ids):
                all_ok = False
            if not self.check_dashboards(dashboard_titles):
                all_ok = False

        return all_ok
