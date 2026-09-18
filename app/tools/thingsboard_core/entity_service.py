"""Entity management service for ThingsBoard REST API.

Provides high-level idempotent CRUD and provisioning operations for Tenants,
Tenant Administrator Users, Devices, Assets, and Inter-entity Relations.

Exported Classes:
    ThingsboardEntityService: Service client for entity hierarchy management.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.entity_service")


class ThingsboardEntityService:
    """Service for managing ThingsBoard entities and relations.

    Provides high-level helper methods to look up or create entities idempotently.

    Attributes:
        http: Authenticated ThingsboardHttpClient instance.
    """

    def __init__(self, http: ThingsboardHttpClient) -> None:
        """Initializes the entity service with an active HTTP client.

        Args:
            http: Authenticated ThingsboardHttpClient instance.
        """
        self.http = http

    # --- Tenants ---
    def get_tenant_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Finds a tenant by title or name across paginated tenant records.

        Args:
            name: Exact tenant title or name string.

        Returns:
            Tenant dictionary if found, else None.
        """
        tenants = self.http.paginated_get("/api/tenants")
        for t in tenants:
            if t.get("name") == name or t.get("title") == name:
                return t
        return None

    def get_or_create_tenant(self, name: str) -> dict[str, Any]:
        """Looks up existing tenant by name or provisions a new one.

        Args:
            name: Name and title of the tenant to locate or create.

        Returns:
            Dictionary representing the existing or newly created tenant entity.
        """
        existing = self.get_tenant_by_name(name)
        if existing:
            return existing
        res = self.http.post("/api/tenant", data={"title": name, "name": name})
        logger.info("✓ Tenant '%s' created (ID: %s)", name, res.get("id", {}).get("id"))
        return res

    # --- Users ---
    def get_user_by_email(self, tenant_id: str, email: str) -> Optional[dict[str, Any]]:
        """Looks up a user within a tenant by email address.

        Args:
            tenant_id: UUID of the target tenant.
            email: Email address of the user to find.

        Returns:
            User dictionary if found, else None.
        """
        users = self.http.paginated_get(f"/api/tenant/{tenant_id}/users")
        for u in users:
            if u.get("email") == email:
                return u
        return None

    def get_user_activation_link(self, user_id: str) -> Optional[str]:
        """Retrieves the plaintext activation link and activation token for a user.

        Args:
            user_id: UUID of the newly created user.

        Returns:
            Full activation URL string if available, else None.
        """
        try:
            resp = self.http.get(f"/api/user/{user_id}/activationLink")
            if isinstance(resp, str):
                return resp.strip('"')
        except Exception:
            pass
        return None

    def activate_user(self, user_id: str, password: str) -> bool:
        """Activates a newly created user and sets their initial account password.

        Args:
            user_id: UUID of the pending user.
            password: Plaintext password to activate the account with.

        Returns:
            True if activation completed successfully, False otherwise.
        """
        link = self.get_user_activation_link(user_id)
        if not link:
            return False
        token = None
        if "activateToken=" in link:
            token = link.split("activateToken=", 1)[1].split("&", 1)[0]
        if not token:
            return False
        try:
            self.http.post(
                "/api/noauth/activate",
                data={"activateToken": token, "password": password, "sendActivationMail": False},
            )
            return True
        except Exception as e:
            logger.warning("Activation error for user %s: %s", user_id, e)
            return False

    def get_or_create_tenant_admin(
        self, tenant_id: str, email: str, password: str, tenant_name: str = "Tenant"
    ) -> dict[str, Any]:
        """Provisions or looks up a tenant administrator user account and sets password.

        Args:
            tenant_id: UUID of the parent tenant.
            email: Login email for the administrator.
            password: Initial account password.
            tenant_name: Name used for user lastName metadata.

        Returns:
            User entity dictionary.
        """
        existing = self.get_user_by_email(tenant_id, email)
        if existing:
            return existing
        user_payload = {
            "tenantId": {"id": tenant_id, "entityType": "TENANT"},
            "email": email,
            "authority": "TENANT_ADMIN",
            "firstName": "Admin",
            "lastName": tenant_name,
        }
        res = self.http.post("/api/user?sendActivationMail=false", data=user_payload)
        user_id = res.get("id", {}).get("id")
        if user_id and password:
            self.activate_user(user_id, password)
        logger.info("✓ Tenant admin '%s' created (ID: %s)", email, user_id)
        return res

    # --- Devices ---
    def get_device_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Searches for an existing device by exact device name.

        Args:
            name: Exact name string of the device.

        Returns:
            Device entity dictionary if found, else None.
        """
        try:
            res = self.http.get(f"/api/tenant/devices?deviceName={name}")
            if isinstance(res, dict) and "id" in res:
                return res
        except Exception:
            pass
        return None

    def get_or_create_device(
        self, name: str, device_type: str = "turbine", attributes: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Looks up or provisions a device under the current tenant.

        Args:
            name: Human-readable name for the device.
            device_type: Device profile/type classification.
            attributes: Optional metadata dictionary passed into additionalInfo.

        Returns:
            Device entity dictionary.
        """
        existing = self.get_device_by_name(name)
        if existing:
            return existing
        payload: dict[str, Any] = {"name": name, "type": device_type, "label": name}
        if attributes:
            payload["additionalInfo"] = attributes
        res = self.http.post("/api/device", data=payload)
        logger.info("✓ Device '%s' created (ID: %s)", name, res.get("id", {}).get("id"))
        return res

    # --- Assets ---
    def get_asset_by_name(self, name: str, asset_type: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Looks up an asset by name, optionally filtered by asset type.

        Args:
            name: Exact name string of the asset.
            asset_type: Optional asset type filter (e.g. 'subsystem').

        Returns:
            Asset entity dictionary if found, else None.
        """
        path = f"/api/tenant/assets?type={asset_type}" if asset_type else "/api/tenant/assets"
        assets = self.http.paginated_get(path)
        for a in assets:
            if a.get("name") == name:
                return a
        return None

    def get_or_create_asset(
        self, name: str, asset_type: str, asset_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Provisions or looks up an asset entity with optional explicit deterministic UUID.

        Args:
            name: Asset name and label.
            asset_type: Classification string (e.g. 'subsystem', 'wind-turbine').
            asset_id: Optional deterministic UUID string for the asset.

        Returns:
            Asset entity dictionary.
        """
        existing = self.get_asset_by_name(name, asset_type)
        if existing:
            return existing
        payload: dict[str, Any] = {"name": name, "type": asset_type, "label": name}
        if asset_id:
            payload["id"] = {"id": asset_id, "entityType": "ASSET"}
        try:
            res = self.http.post("/api/asset", data=payload)
        except Exception:
            if asset_id:
                payload.pop("id", None)
                res = self.http.post("/api/asset", data=payload)
            else:
                raise
        logger.info("✓ Asset '%s' created (ID: %s)", name, res.get("id", {}).get("id"))
        return res

    # --- Relations ---
    def create_relation(
        self,
        from_id: str,
        from_type: str,
        to_id: str,
        to_type: str,
        relation_type: str = "Contains",
    ) -> bool:
        """Establishes a directed relation link between two ThingsBoard entities.

        Args:
            from_id: UUID of the source entity.
            from_type: Entity type of the source (e.g. 'ASSET', 'DEVICE').
            to_id: UUID of the destination entity.
            to_type: Entity type of the destination.
            relation_type: Relationship name (e.g. 'Contains', 'Manages').

        Returns:
            True if relation was established, False if creation failed.
        """
        payload = {
            "from": {"id": from_id, "entityType": from_type},
            "to": {"id": to_id, "entityType": to_type},
            "type": relation_type,
            "typeGroup": "COMMON",
        }
        try:
            self.http.post("/api/relation", data=payload)
            return True
        except Exception as e:
            logger.warning("Failed to create relation %s -> %s: %s", from_id, to_id, e)
            return False

