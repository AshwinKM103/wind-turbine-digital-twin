"""Core ThingsBoard management package."""

from __future__ import annotations

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
