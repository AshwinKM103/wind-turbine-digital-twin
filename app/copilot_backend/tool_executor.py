"""Tool execution layer for copilot backend.

Provides a unified, secure dispatch interface for executing read-only diagnostic tools,
validating arguments, binding conversation entity context, and isolating runtime errors.

Exported Classes:
    ToolExecutor: Central dispatcher for ThingsBoard and diagnostic copilot tools.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

try:
    from app.copilot_backend.thingsboard_tools import (
        get_latest_telemetry,
        get_telemetry_range,
        list_alarms,
        get_alarm_details,
        get_sensor_catalog,
        get_operating_limits,
        build_chart_spec,
        ToolError,
    )
except ImportError:
    from thingsboard_tools import (
        get_latest_telemetry,
        get_telemetry_range,
        list_alarms,
        get_alarm_details,
        get_sensor_catalog,
        get_operating_limits,
        build_chart_spec,
        ToolError,
    )

try:
    from app.copilot_backend.anomaly_service import get_analysis_results, AnomalyServiceError
except ImportError:
    from anomaly_service import get_analysis_results, AnomalyServiceError

try:
    from app.copilot_backend.dashboard_actions import build_open_dashboard_action, DashboardActionError
except ImportError:
    from dashboard_actions import build_open_dashboard_action, DashboardActionError

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Encapsulates tool execution with validation, error isolation, and structured logging.

    Attributes:
        tb_client: Optional default ThingsBoard client instance.
    """

    def __init__(self, tb_client: object = None) -> None:
        """Initializes the ToolExecutor with an optional default ThingsBoard client.

        Args:
            tb_client: Optional ThingsboardClient instance.
        """
        self.tb_client = tb_client

    def execute_tool(
        self,
        tool_name: str,
        tool_args_json: str,
        tb_client: object = None,
        resolved_entity: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Executes a diagnostic tool by name with parsed JSON arguments.

        Args:
            tool_name: Identifier of the tool (e.g. 'get_latest_telemetry', 'render_chart').
            tool_args_json: Serialized JSON argument payload string.
            tb_client: Optional override ThingsBoard client instance.
            resolved_entity: Resolved turbine entity context for this conversation.

        Returns:
            JSON-serialized string of the tool result, structured action, or error description.
        """
        client = tb_client or self.tb_client

        try:
            args = json.loads(tool_args_json)
        except json.JSONDecodeError as e:
            return f"ERROR: Failed to parse tool arguments as JSON: {e}"

        if resolved_entity and tool_name in (
            "get_latest_telemetry",
            "get_telemetry_range",
            "list_alarms",
        ):
            args["entity_type"] = resolved_entity["entity_type"]
            args["entity_id"] = resolved_entity["entity_id"]

        try:
            if tool_name == "get_latest_telemetry":
                if not resolved_entity:
                    return "Tool error: no turbine is currently resolved for this conversation"
                result = get_latest_telemetry(
                    client,
                    entity_type=args.get("entity_type"),
                    entity_id=args.get("entity_id"),
                    keys=args.get("keys", []),
                )
                logger.info(
                    "Tool: get_latest_telemetry",
                    extra={
                        "tool_name": "get_latest_telemetry",
                        "entity_type": args.get("entity_type"),
                        "entity_id": args.get("entity_id"),
                        "num_keys": len(args.get("keys", [])),
                        "result_keys": len(result) if isinstance(result, dict) else 0,
                    },
                )
                return json.dumps(result)

            elif tool_name == "get_telemetry_range":
                if not resolved_entity:
                    return "Tool error: no turbine is currently resolved for this conversation"
                result = get_telemetry_range(
                    client,
                    entity_type=args.get("entity_type"),
                    entity_id=args.get("entity_id"),
                    keys=args.get("keys", []),
                    start_ts=args.get("start_ts"),
                    end_ts=args.get("end_ts"),
                    interval_ms=args.get("interval_ms", 0),
                    max_points=args.get("max_points", 500),
                )
                logger.info(
                    "Tool: get_telemetry_range",
                    extra={
                        "tool_name": "get_telemetry_range",
                        "entity_type": args.get("entity_type"),
                        "entity_id": args.get("entity_id"),
                        "start_ts": args.get("start_ts"),
                        "end_ts": args.get("end_ts"),
                        "num_keys": len(args.get("keys", [])),
                        "interval_ms": args.get("interval_ms", 0),
                        "max_points": args.get("max_points", 500),
                    },
                )
                return json.dumps(result)

            elif tool_name == "list_alarms":
                result = list_alarms(
                    client,
                    entity_type=args.get("entity_type"),
                    entity_id=args.get("entity_id"),
                    status=args.get("status"),
                    limit=args.get("limit", 50),
                )
                logger.info(
                    "Tool: list_alarms",
                    extra={
                        "tool_name": "list_alarms",
                        "entity_type": args.get("entity_type"),
                        "entity_id": args.get("entity_id"),
                        "status": args.get("status"),
                        "num_alarms": len(result) if isinstance(result, list) else 0,
                    },
                )
                return json.dumps(result)

            elif tool_name == "get_sensor_catalog":
                result = get_sensor_catalog()
                logger.info(
                    "Tool: get_sensor_catalog",
                    extra={
                        "tool_name": "get_sensor_catalog",
                        "num_sensors": len(result) if isinstance(result, list) else 0,
                    },
                )
                return json.dumps(result)

            elif tool_name == "get_operating_limits":
                result = get_operating_limits(sensor_key=args.get("sensor_key"))
                logger.info(
                    "Tool: get_operating_limits",
                    extra={
                        "tool_name": "get_operating_limits",
                        "sensor_key": args.get("sensor_key"),
                        "found": result is not None,
                    },
                )
                return json.dumps(result)

            elif tool_name == "get_alarm_details":
                result = get_alarm_details(client, alarm_id=args.get("alarm_id"))
                logger.info(
                    "Tool: get_alarm_details",
                    extra={"tool_name": "get_alarm_details", "alarm_id": args.get("alarm_id")},
                )
                return json.dumps(result)

            elif tool_name == "get_analysis_results":
                if not resolved_entity:
                    return "Tool error: no turbine is currently resolved for this conversation"
                try:
                    result = get_analysis_results(
                        client,
                        entity_type=resolved_entity["entity_type"],
                        entity_id=resolved_entity["entity_id"],
                        asset_id=resolved_entity.get("device_name", resolved_entity["entity_id"]),
                        component_id=args.get("component_id"),
                    )
                except AnomalyServiceError as e:
                    logger.warning(f"Anomaly service error: {e}", extra={"tool_name": "get_analysis_results"})
                    return f"Tool error: {e}"
                logger.info(
                    "Tool: get_analysis_results",
                    extra={
                        "tool_name": "get_analysis_results",
                        "component_id": args.get("component_id"),
                        "num_results": len(result),
                    },
                )
                return json.dumps(result)

            elif tool_name == "render_chart":
                if not resolved_entity:
                    return "Tool error: no turbine is currently resolved for this conversation"
                result = build_chart_spec(
                    client,
                    entity_type=resolved_entity["entity_type"],
                    entity_id=resolved_entity["entity_id"],
                    keys=args.get("keys", []),
                    start_ts=args.get("start_ts"),
                    end_ts=args.get("end_ts"),
                    title=args.get("title"),
                )
                logger.info(
                    "Tool: render_chart",
                    extra={"tool_name": "render_chart", "num_series": len(result.get("series", []))},
                )
                return json.dumps({"__structured__": "chart", "spec": result})

            elif tool_name == "open_dashboard":
                try:
                    result = build_open_dashboard_action(args.get("dashboard_key"))
                except DashboardActionError as e:
                    logger.warning(f"Dashboard action error: {e}", extra={"tool_name": "open_dashboard"})
                    return f"Tool error: {e}"
                logger.info(
                    "Tool: open_dashboard",
                    extra={"tool_name": "open_dashboard", "dashboard_key": args.get("dashboard_key")},
                )
                return json.dumps({"__structured__": "ui_action", "action": result})

            else:
                return f"ERROR: Unknown tool: {tool_name}"

        except ToolError as e:
            logger.error(f"Tool error in {tool_name}: {e}", exc_info=True)
            return f"Tool error: {e}"
        except Exception as e:
            logger.error(f"Unexpected error executing {tool_name}: {e}", exc_info=True)
            return f"Internal error executing {tool_name}: {e}"
