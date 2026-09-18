"""Entity service for managing Tenants, Users, Devices, Assets, and Relations."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.entity_service")


class ThingsboardEntityService:
    """Service for managing ThingsBoard entities and relations."""

    def __init__(self, http: ThingsboardHttpClient):
        self.http = http

    # --- Tenants ---
    def get_tenant_by_name(self, name: str) -> Optional[dict[str, Any]]:
        tenants = self.http.paginated_get("/api/tenants")
        for t in tenants:
            if t.get("name") == name or t.get("title") == name:
                return t
        return None

    def get_or_create_tenant(self, name: str) -> dict[str, Any]:
        existing = self.get_tenant_by_name(name)
        if existing:
            return existing
        res = self.http.post("/api/tenant", data={"title": name, "name": name})
        logger.info("✓ Tenant '%s' created (ID: %s)", name, res.get("id", {}).get("id"))
        return res

    # --- Users ---
    def get_user_by_email(self, tenant_id: str, email: str) -> Optional[dict[str, Any]]:
        users = self.http.paginated_get(f"/api/tenant/{tenant_id}/users")
        for u in users:
            if u.get("email") == email:
                return u
        return None

    def get_user_activation_link(self, user_id: str) -> Optional[str]:
        try:
            resp = self.http.get(f"/api/user/{user_id}/activationLink")
            if isinstance(resp, str):
                return resp.strip('"')
        except Exception:
            pass
        return None

    def activate_user(self, user_id: str, password: str) -> bool:
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
        path = f"/api/tenant/assets?type={asset_type}" if asset_type else "/api/tenant/assets"
        assets = self.http.paginated_get(path)
        for a in assets:
            if a.get("name") == name:
                return a
        return None

    def get_or_create_asset(
        self, name: str, asset_type: str, asset_id: Optional[str] = None
    ) -> dict[str, Any]:
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
