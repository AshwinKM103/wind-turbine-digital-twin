"""Widget service for loading, updating, and saving ThingsBoard widget types."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.tools.thingsboard_core.http_client import ThingsboardHttpClient

logger = logging.getLogger("tb_core.widget_service")


class ThingsboardWidgetService:
    """Service for managing ThingsBoard widget types."""

    def __init__(self, http: ThingsboardHttpClient):
        self.http = http

    def load_widget_file(self, path: Path) -> dict[str, Any]:
        """Loads and parses JSON widget descriptor from disk."""
        return json.loads(path.read_text(encoding="utf-8"))

    def get_widget_by_fqn(self, fqn: str) -> Optional[dict[str, Any]]:
        """Queries ThingsBoard for a widget type by its full FQN (e.g. tenant.xxx)."""
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
        """Idempotently creates or updates a widget type checking FQN."""
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
