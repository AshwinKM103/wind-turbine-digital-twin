"""State and entity management services for ThingsBoard dashboards and telemetry."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.state_service")


class ThingsboardDashboardService:
    """Service for managing ThingsBoard dashboards."""

    def __init__(self, http: ThingsboardHttpClient):
        self.http = http

    def list_dashboards(self, page_size: int = 100) -> list[dict[str, Any]]:
        return self.http.paginated_get("/api/tenant/dashboards", page_size=page_size)

    def get_dashboard_by_title(self, title: str) -> Optional[dict[str, Any]]:
        for d in self.list_dashboards():
            if d.get("title") == title:
                return d
        return None

    def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/dashboard/{dashboard_id}")

    def save_dashboard(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        res = self.http.post("/api/dashboard", data=dashboard_data)
        d_id = res.get("id", {}).get("id") if isinstance(res, dict) else res
        logger.info("✓ Dashboard '%s' saved (ID: %s)", dashboard_data.get("title"), d_id)
        return res

    def get_or_create_dashboard(self, title: str, configuration: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        existing = self.get_dashboard_by_title(title)
        if existing:
            d_id = existing.get("id", {}).get("id")
            return self.get_dashboard(d_id)
        payload: dict[str, Any] = {
            "title": title,
            "configuration": configuration or {"widgets": {}, "states": {"default": {"name": title, "root": True, "layouts": {"main": {"widgets": {}}}}}},
        }
        return self.save_dashboard(payload)

    def delete_dashboard(self, dashboard_id: str) -> bool:
        return self.http.delete(f"/api/dashboard/{dashboard_id}")


class ThingsboardTelemetryService:
    """Service for managing attributes and telemetry on ThingsBoard entities."""

    def __init__(self, http: ThingsboardHttpClient):
        self.http = http

    def save_attributes(
        self,
        entity_type: str,
        entity_id: str,
        attributes: dict[str, Any],
        scope: str = "SERVER_SCOPE",
    ) -> bool:
        path = f"/api/plugins/telemetry/{entity_type}/{entity_id}/{scope}"
        try:
            self.http.post(path, data=attributes)
            return True
        except Exception as e:
            logger.warning("Failed to save attributes to %s/%s: %s", entity_type, entity_id, e)
            return False

    def get_attributes(
        self,
        entity_type: str,
        entity_id: str,
        scope: str = "SERVER_SCOPE",
        keys: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        path = f"/api/plugins/telemetry/{entity_type}/{entity_id}/values/attributes/{scope}"
        params = {"keys": ",".join(keys)} if keys else None
        res = self.http.get(path, params=params)
        return res if isinstance(res, list) else []

    def save_telemetry(
        self,
        entity_type: str,
        entity_id: str,
        telemetry: dict[str, Any],
    ) -> bool:
        path = f"/api/plugins/telemetry/{entity_type}/{entity_id}/timeseries/ANY"
        try:
            self.http.post(path, data=telemetry)
            return True
        except Exception as e:
            logger.warning("Failed to save telemetry to %s/%s: %s", entity_type, entity_id, e)
            return False


DashboardStateManager = ThingsboardDashboardService
TelemetryStateManager = ThingsboardTelemetryService
