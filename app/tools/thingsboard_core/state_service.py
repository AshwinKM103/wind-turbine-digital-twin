"""State and entity management services for ThingsBoard dashboards and telemetry.

Provides high-level APIs for dashboard life-cycle operations (create, read, update, delete)
and entity state persistence (timeseries telemetry and scoped attributes).

Exported Classes:
    ThingsboardDashboardService: Service client for dashboard layout and state persistence.
    ThingsboardTelemetryService: Service client for attributes and timeseries ingestion.
    DashboardStateManager: Alias for ThingsboardDashboardService.
    TelemetryStateManager: Alias for ThingsboardTelemetryService.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.state_service")


class ThingsboardDashboardService:
    """Service for managing ThingsBoard dashboards and UI configurations.

    Attributes:
        http: Authenticated ThingsboardHttpClient instance.
    """

    def __init__(self, http: ThingsboardHttpClient) -> None:
        """Initializes the dashboard service.

        Args:
            http: Authenticated ThingsboardHttpClient instance.
        """
        self.http = http

    def list_dashboards(self, page_size: int = 100) -> list[dict[str, Any]]:
        """Lists all tenant dashboards across pages.

        Args:
            page_size: Number of dashboards per page request.

        Returns:
            List of dashboard summary dictionaries.
        """
        return self.http.paginated_get("/api/tenant/dashboards", page_size=page_size)

    def get_dashboard_by_title(self, title: str) -> Optional[dict[str, Any]]:
        """Finds a dashboard by its exact title.

        Args:
            title: Dashboard title string.

        Returns:
            Dashboard dictionary if located, else None.
        """
        for d in self.list_dashboards():
            if d.get("title") == title:
                return d
        return None

    def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        """Retrieves full dashboard configuration and layout by UUID.

        Args:
            dashboard_id: UUID of the dashboard.

        Returns:
            Complete dashboard configuration dictionary.
        """
        return self.http.get(f"/api/dashboard/{dashboard_id}")

    def save_dashboard(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        """Creates or updates a dashboard configuration payload.

        Args:
            dashboard_data: Complete dashboard payload dictionary.

        Returns:
            Saved dashboard entity response from ThingsBoard.
        """
        res = self.http.post("/api/dashboard", data=dashboard_data)
        d_id = res.get("id", {}).get("id") if isinstance(res, dict) else res
        logger.info("✓ Dashboard '%s' saved (ID: %s)", dashboard_data.get("title"), d_id)
        return res

    def get_or_create_dashboard(
        self, title: str, configuration: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Retrieves existing dashboard by title or provisions a new blank one.

        Args:
            title: Title for the dashboard.
            configuration: Optional custom layout and widget configuration dictionary.

        Returns:
            Full dashboard entity dictionary.
        """
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
        """Deletes a dashboard by UUID.

        Args:
            dashboard_id: UUID string of the dashboard to remove.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        return self.http.delete(f"/api/dashboard/{dashboard_id}")


class ThingsboardTelemetryService:
    """Service for managing attributes and telemetry on ThingsBoard entities.

    Attributes:
        http: Authenticated ThingsboardHttpClient instance.
    """

    def __init__(self, http: ThingsboardHttpClient) -> None:
        """Initializes the telemetry service.

        Args:
            http: Authenticated ThingsboardHttpClient instance.
        """
        self.http = http

    def save_attributes(
        self,
        entity_type: str,
        entity_id: str,
        attributes: dict[str, Any],
        scope: str = "SERVER_SCOPE",
    ) -> bool:
        """Saves attributes to a target entity within a specific scope.

        Args:
            entity_type: Entity classification (e.g. 'DEVICE', 'ASSET').
            entity_id: UUID string of the entity.
            attributes: Key-value mapping of attribute values to set.
            scope: Target attribute scope ('SERVER_SCOPE', 'SHARED_SCOPE', etc.).

        Returns:
            True if attributes saved successfully, False on error.
        """
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
        """Fetches attributes for an entity within a given scope.

        Args:
            entity_type: Entity classification (e.g. 'DEVICE', 'ASSET').
            entity_id: UUID string of the entity.
            scope: Attribute scope to query.
            keys: Optional list of attribute key names to filter.

        Returns:
            List of attribute dictionaries with key, lastUpdateTs, and value.
        """
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
        """Publishes timeseries telemetry datapoints to an entity.

        Args:
            entity_type: Entity classification (e.g. 'DEVICE', 'ASSET').
            entity_id: UUID string of the entity.
            telemetry: Key-value dictionary of telemetry measurements.

        Returns:
            True if telemetry successfully accepted, False otherwise.
        """
        path = f"/api/plugins/telemetry/{entity_type}/{entity_id}/timeseries/ANY"
        try:
            self.http.post(path, data=telemetry)
            return True
        except Exception as e:
            logger.warning("Failed to save telemetry to %s/%s: %s", entity_type, entity_id, e)
            return False


DashboardStateManager = ThingsboardDashboardService
TelemetryStateManager = ThingsboardTelemetryService

