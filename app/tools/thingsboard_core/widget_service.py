"""Widget type management service for ThingsBoard REST API.

Provides functionality for loading widget descriptors from JSON files, querying
widget types by Fully Qualified Name (FQN), and creating or updating widget bundles
idempotently within tenant scope.

Exported Classes:
    ThingsboardWidgetService: Service client for widget bundle persistence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.widget_service")


class ThingsboardWidgetService:
    """Service for managing ThingsBoard widget types.

    Attributes:
        http: Authenticated ThingsboardHttpClient instance.
    """

    def __init__(self, http: ThingsboardHttpClient) -> None:
        """Initializes the widget service.

        Args:
            http: Authenticated ThingsboardHttpClient instance.
        """
        self.http = http

    def load_widget_file(self, path: Path) -> dict[str, Any]:
        """Loads and parses JSON widget descriptor from disk.

        Args:
            path: Path to the JSON descriptor file on disk.

        Returns:
            Parsed widget descriptor dictionary.
        """
        return json.loads(path.read_text(encoding="utf-8"))

    def get_widget_by_fqn(self, fqn: str) -> Optional[dict[str, Any]]:
        """Queries ThingsBoard for a widget type by its full FQN.

        Args:
            fqn: Fully qualified name string (e.g. 'tenant.turbine_3d_babylon').

        Returns:
            Widget type dictionary if found, else None.
        """
        bare_fqn = fqn.removeprefix("tenant.").removeprefix("system.")
        full_fqn = f"tenant.{bare_fqn}"
        try:
            res = self.http.get(f"/api/widgetType?fqn={full_fqn}")
            if isinstance(res, dict) and "id" in res:
                return res
        except Exception:
            pass
        return None

    def save_or_update_widget_type(
        self,
        descriptor: dict[str, Any],
        fqn: Optional[str] = None,
        name: Optional[str] = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Idempotently creates or updates a widget type checking FQN.

        Args:
            descriptor: Widget descriptor containing HTML/CSS/JS and schemas.
            fqn: Optional explicit FQN key.
            name: Optional human-readable display title for widget.
            description: Optional textual summary of widget behavior.

        Returns:
            Saved widget type dictionary response from ThingsBoard.
        """
        bare_fqn = (fqn or descriptor.get("fqn", "")).removeprefix("tenant.").removeprefix("system.")
        full_fqn = f"tenant.{bare_fqn}"
        widget_name = name or descriptor.get("name") or bare_fqn

        existing = self.get_widget_by_fqn(full_fqn)
        existing_id = existing.get("id", {}).get("id") if existing else None

        desc = descriptor.get("descriptor", descriptor)
        if not desc.get("defaultConfig"):
            desc["defaultConfig"] = json.dumps({
                "datasources": [],
                "timewindow": {"realtime": {"timewindowMs": 60000}},
                "showTitle": False,
                "backgroundColor": "transparent",
                "color": "rgba(255,255,255,0.87)",
                "padding": "0px",
                "settings": {},
                "title": widget_name,
            })

        payload: dict[str, Any] = {
            "fqn": bare_fqn,
            "name": widget_name,
            "deprecated": descriptor.get("deprecated", False),
            "scada": descriptor.get("scada", False),
            "description": description or descriptor.get("description", ""),
            "descriptor": desc,
        }
        if existing_id:
            payload["id"] = {"entityType": "WIDGET_TYPE", "id": existing_id}

        res = self.http.post("/api/widgetType", data=payload)
        wid = res.get("id", {}).get("id") if isinstance(res, dict) else res
        logger.info("✓ Saved widget %s (%s) -> ID: %s", widget_name, full_fqn, wid)
        return res

