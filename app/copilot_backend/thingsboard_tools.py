"""Read-only ThingsBoard copilot backend tools for telemetry, alarms, and sensor catalog.

Provides safe, bounded, read-only access to ThingsBoard telemetry data, alarm history,
and static subsystem sensor metadata. No write, RPC, or alarm-acknowledgment operations.

Exported Classes:
    ToolError: Raised for any tool execution failure, validation error, or missing entity.

Exported Functions:
    get_latest_telemetry: Fetches current value and timestamp for requested keys.
    get_telemetry_range: Queries aggregated timeseries datapoints across a time window.
    list_alarms: Lists alarm events filtered by severity, status, and entity.
    get_alarm_details: Retrieves granular metadata for a specific alarm.
    get_sensor_catalog: Returns static mapping of turbine sensors and descriptions.
    get_operating_limits: Queries ISO and engineering warning/critical thresholds.
    build_chart_spec: Builds frontend chart rendering specification.
"""


from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

# Import ThingsboardClient (caller must provide authenticated instance)
# Note: do NOT call authenticate() or create credentials in this module
try:
    from app.tools.thingsboard_client import ThingsboardClient
except ImportError:
    from tools.thingsboard_client import ThingsboardClient

# Import subsystem registry for sensor catalog and operating limits
try:
    from app.tools.subsystem_registry import (
        SUBSYSTEMS,
        ScoredSensor,
        SensorLimits,
        resolve_limits,
    )
except ImportError:
    from tools.subsystem_registry import (
        SUBSYSTEMS,
        ScoredSensor,
        SensorLimits,
        resolve_limits,
    )

logger = logging.getLogger("tb_tools")

# Constants
THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000
DEFAULT_MAX_POINTS = 500
DEFAULT_INTERVAL_MS = 1000

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# fleet.json lives at app/config/fleet.json; this module lives at app/copilot_backend/.
_FLEET_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "fleet.json"


class ToolError(Exception):
    """Raised for any tool failure: bad response, timeout, missing entity, validation error, etc."""

    pass


def _coerce_numeric(value: Any) -> Any:
    """Converts a numeric-looking string to float; passes through anything else.

    ThingsBoard's aggregated telemetry endpoint (agg=AVG/MIN/MAX/...) returns
    "value" as a string even for numeric series. Non-numeric telemetry (state
    labels, etc.) is left untouched.
    """
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def resolve_turbine_device(client: ThingsboardClient, turbine_id: str) -> dict[str, str]:
    """Resolve a dashboard-supplied turbine identifier to a real ThingsBoard device.

    This is the server-side validation step the architecture requires: the widget
    (and the LLM) must never be trusted to supply a correct ThingsBoard entity_id
    directly. This function looks the turbine up against fleet.json (to build the
    expected "{customer}.{site}.{turbine}" device name) and then confirms that
    device actually exists in ThingsBoard, returning its real entity_type/entity_id.

    Args:
        client: Authenticated ThingsboardClient instance.
        turbine_id: Turbine identifier from the dashboard context (e.g. "boreas"),
                    or a raw ThingsBoard device UUID.

    Returns:
        {"entity_type": "DEVICE", "entity_id": "<uuid>", "device_name": "<tb name>"}

    Raises:
        ToolError: If turbine_id is empty or cannot be resolved to an existing device.
    """
    if not turbine_id:
        raise ToolError("turbine_id is required to resolve a device")

    if _UUID_RE.match(turbine_id):
        # Caller already supplied a device UUID (e.g. a future widget version);
        # still verify it against the live registry rather than trusting it blindly.
        for device in client.list_devices():
            if device.get("id", {}).get("id") == turbine_id:
                return {
                    "entity_type": "DEVICE",
                    "entity_id": turbine_id,
                    "device_name": device.get("name", turbine_id),
                }
        raise ToolError(f"No ThingsBoard device found with id '{turbine_id}'")

    candidate_names: list[str] = []
    try:
        with open(_FLEET_CONFIG_PATH, "r", encoding="utf-8") as f:
            fleet = json.load(f)
        for customer in fleet.get("customers", []):
            for site in customer.get("sites", []):
                for turbine in site.get("turbines", []):
                    if turbine.get("turbine_id") == turbine_id:
                        candidate_names.append(
                            f"{customer['customer_id']}.{site['site_id']}.{turbine_id}"
                        )
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Could not load fleet.json for turbine resolution: {e}")

    # Fall back to treating turbine_id itself as the device name.
    candidate_names.append(turbine_id)

    for name in candidate_names:
        device = client.find_device_by_name(name)
        if device:
            device_id = device.get("id", {}).get("id")
            if device_id:
                return {"entity_type": "DEVICE", "entity_id": device_id, "device_name": name}

    raise ToolError(
        f"Could not resolve turbine_id '{turbine_id}' to a known ThingsBoard device "
        f"(tried names: {candidate_names})"
    )


def get_latest_telemetry(
    client: ThingsboardClient,
    entity_type: str,
    entity_id: str,
    keys: list[str],
) -> dict[str, Any]:
    """Fetch the latest telemetry values for a device or asset.

    Calls GET /api/plugins/telemetry/{entityType}/{entityId}/values/timeseries?keys=k1,k2,...

    Args:
        client: Authenticated ThingsboardClient instance.
        entity_type: Entity type (e.g., "DEVICE", "ASSET").
        entity_id: Entity ID (UUID).
        keys: List of telemetry keys to fetch.

    Returns:
        dict mapping each key to {"value": ..., "ts": ...}, e.g.
        {"temperature": {"value": 42.5, "ts": 1234567890000}, ...}

    Raises:
        ToolError: If the request fails, times out, or returns malformed data.
    """
    if not keys:
        return {}

    keys_str = ",".join(keys)
    endpoint = f"/api/plugins/telemetry/{entity_type}/{entity_id}/values/timeseries?keys={keys_str}"

    try:
        resp = client._request("GET", endpoint)
        if resp.status_code not in (200, 201):
            raise ToolError(
                f"GET {endpoint} returned HTTP {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        if not isinstance(data, dict):
            raise ToolError(
                f"GET {endpoint} returned non-dict body: {type(data).__name__}"
            )

        # ThingsBoard returns {key: [{value: ..., ts: ...}, ...]}
        # We return {key: {value: ..., ts: ...}} (latest only)
        result = {}
        for key, values in data.items():
            if isinstance(values, list) and len(values) > 0:
                latest = values[0]  # TB returns sorted descending by timestamp
                if isinstance(latest, dict) and "value" in latest and "ts" in latest:
                    result[key] = {"value": latest["value"], "ts": latest["ts"]}

        return result

    except ToolError:
        raise
    except Exception as e:
        raise ToolError(
            f"Failed to fetch latest telemetry from {endpoint}: {type(e).__name__}: {e}"
        )


def get_telemetry_range(
    client: ThingsboardClient,
    entity_type: str,
    entity_id: str,
    keys: list[str],
    start_ts: int,
    end_ts: int,
    interval_ms: int = 0,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, Any]:
    """Fetch telemetry in a time range with automatic aggregation to prevent unbounded queries.

    Calls GET /api/plugins/telemetry/{entityType}/{entityId}/values/timeseries
    with startTs, endTs, and optional aggregation parameters.

    CRITICAL SAFETY RULE: If the raw sample count would exceed max_points, automatic
    aggregation is applied (agg=AVG, interval calculated). The caller receives at most
    max_points buckets per key.

    Args:
        client: Authenticated ThingsboardClient instance.
        entity_type: Entity type (e.g., "DEVICE", "ASSET").
        entity_id: Entity ID (UUID).
        keys: List of telemetry keys to fetch.
        start_ts: Start timestamp (milliseconds since epoch).
        end_ts: End timestamp (milliseconds since epoch).
        interval_ms: Minimum aggregation interval in milliseconds (0 = auto).
        max_points: Maximum points per key in response (default 500). Returns wrapped
                    in {"data": ..., "truncated": bool, "interval_ms": int}.

    Returns:
        dict wrapping the telemetry series:
        {
            "data": {key: [{ts: ..., value: ...}, ...]},
            "truncated": bool (True if aggregation was applied),
            "interval_ms": int (aggregation interval used, or 0 if no aggregation)
        }

    Raises:
        ToolError: If start_ts >= end_ts, range > 30 days, request fails, or response
                   is malformed.
    """
    if not keys:
        return {"data": {}, "truncated": False, "interval_ms": 0}

    if start_ts >= end_ts:
        raise ToolError(f"start_ts ({start_ts}) must be < end_ts ({end_ts})")

    range_ms = end_ts - start_ts
    if range_ms > THIRTY_DAYS_MS:
        raise ToolError(
            f"Time range ({range_ms} ms = {range_ms // THIRTY_DAYS_MS} days) "
            f"exceeds 30-day limit. Truncate the query."
        )

    keys_str = ",".join(keys)
    query_params = f"keys={keys_str}&startTs={start_ts}&endTs={end_ts}"

    # Calculate required aggregation interval to keep response bounded
    truncated = False
    agg_interval = interval_ms
    if interval_ms == 0:
        # Raw sample count: divide range by ~minimum sample period
        raw_estimate = range_ms // 1000  # assumes 1s interval at minimum
        if raw_estimate > max_points:
            truncated = True
            agg_interval = max(1000, (range_ms // max_points))
            query_params += f"&agg=AVG&interval={agg_interval}"

    endpoint = f"/api/plugins/telemetry/{entity_type}/{entity_id}/values/timeseries?{query_params}"

    try:
        resp = client._request("GET", endpoint)
        if resp.status_code not in (200, 201):
            raise ToolError(
                f"GET {endpoint} returned HTTP {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        if not isinstance(data, dict):
            raise ToolError(
                f"GET {endpoint} returned non-dict body: {type(data).__name__}"
            )

        # ThingsBoard returns {key: [{ts: ..., value: ...}, ...]}. Aggregated
        # (AVG/MIN/MAX/...) responses in particular carry "value" as a
        # numeric-looking *string* ("32.68..."), not a JSON number — coerce
        # it here so downstream consumers (render_chart's widget-side type
        # check, the anomaly-detection service) get real numbers rather than
        # silently dropping every point.
        result = {}
        for key, values in data.items():
            if isinstance(values, list):
                result[key] = [
                    {"ts": v.get("ts"), "value": _coerce_numeric(v.get("value"))}
                    for v in values
                    if isinstance(v, dict) and "ts" in v and "value" in v
                ]

        return {
            "data": result,
            "truncated": truncated,
            "interval_ms": agg_interval if truncated else 0,
        }

    except ToolError:
        raise
    except Exception as e:
        raise ToolError(
            f"Failed to fetch telemetry range from {endpoint}: {type(e).__name__}: {e}"
        )


def list_alarms(
    client: ThingsboardClient,
    entity_type: str,
    entity_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch alarms for a device or asset (read-only list only, no acknowledgment).

    Calls GET /api/alarm/{entityType}/{entityId}?pageSize=limit&page=0[&status=status]

    Each alarm in the response is mapped to a compact dict with id, type, severity,
    status, createdTime, ackTime, clearTime.

    Args:
        client: Authenticated ThingsboardClient instance.
        entity_type: Entity type (e.g., "DEVICE", "ASSET").
        entity_id: Entity ID (UUID).
        status: Optional filter by exact ThingsBoard AlarmSearchStatus enum value:
                "ACTIVE_UNACK", "ACTIVE_ACK", "CLEARED_UNACK", or "CLEARED_ACK".
                Any other value (e.g. "ACTIVE" alone, "ANY") is rejected by the
                ThingsBoard API with HTTP 400.
        limit: Maximum alarms to fetch (default 50, max 100).

    Returns:
        list of dicts, each with keys: id, type, severity, status, createdTime, ackTime, clearTime.
        Empty list if no alarms found.

    Raises:
        ToolError: If the request fails, times out, or response is malformed.
    """
    limit = min(limit, 100)  # Cap at 100 per request
    endpoint = f"/api/alarm/{entity_type}/{entity_id}?pageSize={limit}&page=0"
    if status:
        endpoint += f"&status={status}"

    try:
        resp = client._request("GET", endpoint)
        if resp.status_code not in (200, 201):
            raise ToolError(
                f"GET {endpoint} returned HTTP {resp.status_code}: {resp.text}"
            )

        body = resp.json()
        alarms = []

        # Handle paginated response { data: [...], hasNext: bool, ... }
        if isinstance(body, dict):
            alarm_list = body.get("data", [])
        elif isinstance(body, list):
            alarm_list = body
        else:
            raise ToolError(
                f"GET {endpoint} returned unexpected type: {type(body).__name__}"
            )

        for alarm in alarm_list:
            if not isinstance(alarm, dict):
                continue

            alarm_id = alarm.get("id")
            if isinstance(alarm_id, dict):
                alarm_id = alarm_id.get("id")

            compact = {
                "id": alarm_id,
                "type": alarm.get("type"),
                "severity": alarm.get("severity"),
                "status": alarm.get("status"),
                "createdTime": alarm.get("createdTime"),
                "ackTime": alarm.get("ackTime"),
                "clearTime": alarm.get("clearTime"),
            }
            alarms.append(compact)

        return alarms

    except ToolError:
        raise
    except Exception as e:
        raise ToolError(
            f"Failed to list alarms from {endpoint}: {type(e).__name__}: {e}"
        )


def get_alarm_details(
    client: ThingsboardClient,
    alarm_id: str,
) -> dict[str, Any]:
    """Fetch full detail for a single alarm by ID (read-only, no acknowledgment).

    Calls GET /api/alarm/info/{alarmId}, which returns the same fields as the
    list endpoint plus the originator entity and any propagation info.

    Args:
        client: Authenticated ThingsboardClient instance.
        alarm_id: Alarm UUID, normally taken from a prior list_alarms result.

    Returns:
        dict with keys: id, type, severity, status, createdTime, ackTime,
        clearTime, originator (entity_type/entity_id), details (raw alarm
        details payload, if any).

    Raises:
        ToolError: If alarm_id is empty, the request fails, or the response
                   is malformed.
    """
    if not alarm_id:
        raise ToolError("alarm_id is required")

    endpoint = f"/api/alarm/info/{alarm_id}"

    try:
        resp = client._request("GET", endpoint)
        if resp.status_code == 404:
            raise ToolError(f"No alarm found with id '{alarm_id}'")
        if resp.status_code not in (200, 201):
            raise ToolError(
                f"GET {endpoint} returned HTTP {resp.status_code}: {resp.text}"
            )

        alarm = resp.json()
        if not isinstance(alarm, dict):
            raise ToolError(
                f"GET {endpoint} returned non-dict body: {type(alarm).__name__}"
            )

        alarm_uuid = alarm.get("id")
        if isinstance(alarm_uuid, dict):
            alarm_uuid = alarm_uuid.get("id")

        originator = alarm.get("originator") or {}

        return {
            "id": alarm_uuid,
            "type": alarm.get("type"),
            "severity": alarm.get("severity"),
            "status": alarm.get("status"),
            "createdTime": alarm.get("createdTime"),
            "ackTime": alarm.get("ackTime"),
            "clearTime": alarm.get("clearTime"),
            "originator": {
                "entity_type": originator.get("entityType"),
                "entity_id": originator.get("id"),
            },
            "details": alarm.get("details"),
        }

    except ToolError:
        raise
    except Exception as e:
        raise ToolError(
            f"Failed to fetch alarm details from {endpoint}: {type(e).__name__}: {e}"
        )


def build_chart_spec(
    client: ThingsboardClient,
    entity_type: str,
    entity_id: str,
    keys: list[str],
    start_ts: int,
    end_ts: int,
    title: str | None = None,
    max_points: int = DEFAULT_MAX_POINTS,
) -> dict[str, Any]:
    """Builds a bounded declarative chart spec for the copilot widget to render.

    Reuses get_telemetry_range's own bounds (30-day range cap, max_points
    aggregation) rather than duplicating them — this is not a second data
    path, just a presentation-shaped wrapper around the same tool.

    Returns:
        {
            "chart_type": "line",
            "title": str,
            "series": [{"key": str, "points": [{"ts": int, "value": float}, ...]}],
            "truncated": bool
        }

    Raises:
        ToolError: propagated from get_telemetry_range (bad range, request failure, etc.)
    """
    range_result = get_telemetry_range(
        client, entity_type, entity_id, keys, start_ts, end_ts, max_points=max_points
    )
    series = [
        {"key": key, "points": points}
        for key, points in range_result["data"].items()
    ]
    return {
        "chart_type": "line",
        "title": title or ", ".join(keys),
        "series": series,
        "truncated": range_result["truncated"],
    }


def get_sensor_catalog() -> list[dict[str, Any]]:
    """Flatten the subsystem registry into a sensor catalog without network calls.

    Iterates SUBSYSTEMS from subsystem_registry and produces a flat list of sensors
    with their subsystem context and operating limits (both primary_sensors and scored_sensors).

    Returns:
        List of dicts, each with keys:
        - sensor_key: str
        - subsystem_name: str
        - subsystem_asset_id: str
        - warn: float | None
        - alarm: float | None
        - critical: float | None
        - source: str | None

    Raises:
        ToolError: If registry iteration fails (should not happen in normal operation).
    """
    catalog = []

    try:
        for subsystem in SUBSYSTEMS:
            # Add primary sensors (no scored limits)
            for sensor_key in subsystem.primary_sensors:
                catalog.append(
                    {
                        "sensor_key": sensor_key,
                        "subsystem_name": subsystem.name,
                        "subsystem_asset_id": subsystem.asset_id,
                        "warn": None,
                        "alarm": None,
                        "critical": None,
                        "source": None,
                    }
                )

            # Add scored sensors with resolved limits
            for scored_sensor in subsystem.scored_sensors:
                limits = resolve_limits(scored_sensor, {})
                catalog.append(
                    {
                        "sensor_key": scored_sensor.key,
                        "subsystem_name": subsystem.name,
                        "subsystem_asset_id": subsystem.asset_id,
                        "warn": limits.warn,
                        "alarm": limits.alarm,
                        "critical": limits.critical,
                        "source": limits.source,
                    }
                )

        return catalog

    except Exception as e:
        raise ToolError(
            f"Failed to build sensor catalog from subsystem_registry: {type(e).__name__}: {e}"
        )


def get_operating_limits(sensor_key: str) -> dict[str, Any] | None:
    """Lookup operating limits for a sensor by key (no network call).

    Searches the subsystem registry for a ScoredSensor matching sensor_key,
    resolves its limits, and returns the limit dict. Returns None if not found
    in any subsystem's scored_sensors.

    Args:
        sensor_key: Telemetry key to look up (e.g., "PT_109A", "XT_600").

    Returns:
        dict with keys: warn, alarm, critical, source. Or None if sensor not found.

    Raises:
        ToolError: If registry lookup fails (should not happen in normal operation).
    """
    try:
        for subsystem in SUBSYSTEMS:
            for scored_sensor in subsystem.scored_sensors:
                if scored_sensor.key == sensor_key:
                    limits = resolve_limits(scored_sensor, {})
                    return {
                        "warn": limits.warn,
                        "alarm": limits.alarm,
                        "critical": limits.critical,
                        "source": limits.source,
                    }
        return None

    except Exception as e:
        raise ToolError(
            f"Failed to lookup operating limits for sensor {sensor_key}: {type(e).__name__}: {e}"
        )
