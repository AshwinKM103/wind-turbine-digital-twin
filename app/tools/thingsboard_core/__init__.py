"""Core ThingsBoard REST API integration and client package.

Provides typed HTTP client sessions, entity management services, dashboard state
manipulation, ECharts visualization generation, and custom widget deployment.

Exported Classes:
    ThingsboardConfig: Configuration container for ThingsBoard connectivity.
    ThingsboardSession: Authentication state and token holder.
    ThingsboardHttpClient: Low-level REST API client with retry semantics.
    ThingsboardEntityService: CRUD operations for devices, assets, and relations.
    ThingsboardWidgetService: Deployment and inspection of widget bundles.
    ThingsboardDashboardService: Provisioning and layout management for dashboards.
    ThingsboardTelemetryService: Querying and publishing entity telemetry/attributes.
    ThingsboardError, ThingsboardAuthError, ThingsboardAPIError: Custom exception types.
"""

from app.tools.thingsboard_core.thingsboard_config import ThingsboardConfig, resolve_config
from app.tools.thingsboard_core.echarts_builder import build_chart_widget, make_axis, make_orbit
from app.tools.thingsboard_core.entity_service import ThingsboardEntityService
from app.tools.thingsboard_core.exceptions import (
    ThingsboardAPIError,
    ThingsboardAuthError,
    ThingsboardError,
)
from app.tools.thingsboard_core.http_client import ThingsboardHttpClient, ThingsboardSession
from app.tools.thingsboard_core.state_service import (
    DashboardStateManager,
    TelemetryStateManager,
    ThingsboardDashboardService,
    ThingsboardTelemetryService,
)
from app.tools.thingsboard_core.widget_service import ThingsboardWidgetService

__all__ = [
    "ThingsboardConfig",
    "resolve_config",
    "ThingsboardSession",
    "ThingsboardHttpClient",
    "ThingsboardEntityService",
    "ThingsboardWidgetService",
    "ThingsboardDashboardService",
    "ThingsboardTelemetryService",
    "DashboardStateManager",
    "TelemetryStateManager",
    "ThingsboardError",
    "ThingsboardAuthError",
    "ThingsboardAPIError",
    "make_axis",
    "make_orbit",
    "build_chart_widget",
]
