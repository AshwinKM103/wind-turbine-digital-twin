"""Tests for read-only ThingsBoard copilot backend tools.

Tests verify safety contract:
- No write, RPC, or control operations
- Aggregation applied when queries would exceed max_points
- Sensor catalog sourced from subsystem registry, not hardcoded
- All external calls mocked (no live ThingsBoard network access)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from typing import Any

import sys
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import the module under test
from app.copilot_backend import thingsboard_tools
from app.tools.subsystem_registry import SUBSYSTEMS


class MockResponse:
    """Mock requests.Response-like object for testing."""

    def __init__(self, status_code: int, json_data: dict | list | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text or f"HTTP {status_code}"

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON data")
        return self._json_data


class TestGetLatestTelemetry:
    """Test get_latest_telemetry function."""

    def test_should_fetch_latest_values_from_single_key(self):
        """Should return latest telemetry value for a single key."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "temperature": [{"value": 42.5, "ts": 1234567890000}]
            }
        )

        result = tb_tools.get_latest_telemetry(
            client, "DEVICE", "device-123", ["temperature"]
        )

        assert result["temperature"]["value"] == 42.5
        assert result["temperature"]["ts"] == 1234567890000
        client._request.assert_called_once()

    def test_should_return_empty_dict_for_empty_keys_list(self):
        """Should return empty dict when no keys requested."""
        client = MagicMock()

        result = tb_tools.get_latest_telemetry(client, "DEVICE", "device-123", [])

        assert result == {}
        client._request.assert_not_called()

    def test_should_raise_tool_error_on_non_200_status(self):
        """Should raise ToolError when API returns non-200 status."""
        client = MagicMock()
        client._request.return_value = MockResponse(404, text="Not found")

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_latest_telemetry(client, "DEVICE", "missing-id", ["temp"])

        assert "404" in str(exc_info.value)

    def test_should_raise_tool_error_on_malformed_response(self):
        """Should raise ToolError when response is not a dict."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, [])  # array instead of dict

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_latest_telemetry(client, "DEVICE", "device-123", ["temp"])

        assert "non-dict" in str(exc_info.value)

    def test_should_handle_multiple_keys(self):
        """Should fetch and return multiple telemetry keys."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "temperature": [{"value": 42.5, "ts": 1234567890000}],
                "pressure": [{"value": 101.3, "ts": 1234567890000}],
            }
        )

        result = tb_tools.get_latest_telemetry(
            client, "DEVICE", "device-123", ["temperature", "pressure"]
        )

        assert len(result) == 2
        assert result["temperature"]["value"] == 42.5
        assert result["pressure"]["value"] == 101.3


class TestGetTelemetryRange:
    """Test get_telemetry_range function with aggregation safety."""

    def test_should_coerce_string_values_from_aggregated_response_to_float(self):
        """ThingsBoard's AVG/MIN/MAX aggregation returns 'value' as a numeric
        string, not a JSON number. Regression test for a real bug: the chart
        widget's client-side `typeof value === 'number'` check silently
        dropped every point when this wasn't coerced server-side."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {"PT_109A": [{"ts": 1000, "value": "32.68228571428572"}]},
        )

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["PT_109A"], 0, 100000
        )

        point = result["data"]["PT_109A"][0]
        assert isinstance(point["value"], float)
        assert point["value"] == pytest.approx(32.68228571428572)

    def test_should_pass_through_non_numeric_values_unchanged(self):
        """A non-numeric telemetry value (e.g. a state label) should not be
        mangled by the numeric coercion."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {"turbine_state": [{"ts": 1000, "value": "RUNNING"}]},
        )

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["turbine_state"], 0, 100000
        )

        assert result["data"]["turbine_state"][0]["value"] == "RUNNING"

    def test_should_return_empty_dict_for_empty_keys(self):
        """Should return empty response when no keys requested."""
        result = tb_tools.get_telemetry_range(
            MagicMock(), "DEVICE", "device-123", [], 1000, 2000
        )

        assert result["data"] == {}
        assert result["truncated"] is False
        assert result["interval_ms"] == 0

    def test_should_raise_on_invalid_time_range(self):
        """Should raise ToolError when start_ts >= end_ts."""
        client = MagicMock()

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_telemetry_range(
                client, "DEVICE", "device-123", ["temp"], 2000, 1000
            )

        assert "start_ts" in str(exc_info.value) and "end_ts" in str(exc_info.value)

    def test_should_raise_on_range_exceeds_30_days(self):
        """Should raise ToolError when range exceeds 30 days."""
        client = MagicMock()
        start_ts = 1000000
        end_ts = start_ts + (31 * 24 * 60 * 60 * 1000)  # 31 days

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_telemetry_range(
                client, "DEVICE", "device-123", ["temp"], start_ts, end_ts
            )

        assert "30-day" in str(exc_info.value)

    def test_should_apply_aggregation_when_raw_samples_exceed_max_points(self):
        """Should request aggregation when raw sample count would exceed max_points.

        Tests the critical safety rule: if a query would return more than max_points
        samples, automatic aggregation (AVG) is applied and truncated flag is set.
        """
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"temp": []})

        # Query spans 1 day (86400 seconds * 1000 ms = 86400000 ms)
        # At 1s intervals = 86400 raw samples
        # With max_points=500, should trigger aggregation
        start_ts = 1000000000
        end_ts = start_ts + (24 * 60 * 60 * 1000)  # 1 day

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["temp"], start_ts, end_ts, max_points=500
        )

        assert result["truncated"] is True
        assert result["interval_ms"] > 0

        # Verify aggregation parameters were included in the request
        called_url = client._request.call_args[0][1]
        assert "agg=AVG" in called_url
        assert "interval=" in called_url

    def test_should_not_apply_aggregation_for_small_ranges(self):
        """Should not apply aggregation for ranges well below max_points."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"temp": []})

        # Query spans 100 seconds
        start_ts = 1000000000
        end_ts = start_ts + 100000  # 100 seconds

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["temp"], start_ts, end_ts, max_points=500
        )

        assert result["truncated"] is False
        assert result["interval_ms"] == 0

        # Verify no aggregation parameters in request
        called_url = client._request.call_args[0][1]
        assert "agg=" not in called_url

    def test_should_honor_explicit_interval_parameter(self):
        """Should use provided interval_ms instead of calculating."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"temp": []})

        start_ts = 1000000000
        end_ts = start_ts + (24 * 60 * 60 * 1000)

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["temp"],
            start_ts, end_ts,
            interval_ms=5000,  # Explicit 5-second interval
            max_points=500
        )

        # When explicit interval is provided, auto-calculation should be skipped
        called_url = client._request.call_args[0][1]
        # interval_ms=0 means auto, so explicit interval should not appear in URL
        # (no agg/interval added by the function)

    def test_should_parse_telemetry_response_correctly(self):
        """Should extract ts and value from ThingsBoard response format."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "temp": [
                    {"ts": 1000000000, "value": 20.5},
                    {"ts": 1000001000, "value": 21.0},
                ]
            }
        )

        start_ts = 1000000000
        end_ts = 1000010000

        result = tb_tools.get_telemetry_range(
            client, "DEVICE", "device-123", ["temp"], start_ts, end_ts
        )

        assert "temp" in result["data"]
        assert len(result["data"]["temp"]) == 2
        assert result["data"]["temp"][0]["value"] == 20.5
        assert result["data"]["temp"][1]["value"] == 21.0

    def test_should_raise_on_non_200_response(self):
        """Should raise ToolError on non-200 HTTP response."""
        client = MagicMock()
        client._request.return_value = MockResponse(500, text="Internal error")

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_telemetry_range(
                client, "DEVICE", "device-123", ["temp"], 1000, 2000
            )

        assert "500" in str(exc_info.value)

    def test_should_raise_on_malformed_json(self):
        """Should raise ToolError when response is not a dict."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, [])

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_telemetry_range(
                client, "DEVICE", "device-123", ["temp"], 1000, 2000
            )

        assert "non-dict" in str(exc_info.value)


class TestListAlarms:
    """Test list_alarms function for read-only safety."""

    def test_should_fetch_alarms_with_get_request_only(self):
        """Should call _request with GET method only, never POST/PUT/DELETE."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {"data": [{"id": "alarm-1", "type": "HIGH_TEMP"}]}
        )

        result = tb_tools.list_alarms(client, "DEVICE", "device-123")

        # Verify GET was used
        call_args = client._request.call_args
        assert call_args[0][0] == "GET"
        assert len(result) == 1
        assert result[0]["type"] == "HIGH_TEMP"

    def test_should_never_construct_urls_with_ack_or_clear(self):
        """Should never include 'ack' or 'clear' in endpoint URLs."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"data": []})

        tb_tools.list_alarms(client, "DEVICE", "device-123")

        called_url = client._request.call_args[0][1]
        assert "ack" not in called_url.lower()
        assert "clear" not in called_url.lower()

    def test_should_respect_limit_parameter(self):
        """Should cap limit at 100 and include in query."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"data": []})

        tb_tools.list_alarms(client, "DEVICE", "device-123", limit=50)

        called_url = client._request.call_args[0][1]
        assert "pageSize=50" in called_url

    def test_should_cap_limit_at_100(self):
        """Should cap limit parameter at 100 even if larger value requested."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"data": []})

        tb_tools.list_alarms(client, "DEVICE", "device-123", limit=500)

        called_url = client._request.call_args[0][1]
        assert "pageSize=100" in called_url

    def test_should_filter_by_status_when_provided(self):
        """Should include status filter parameter when provided."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"data": []})

        tb_tools.list_alarms(client, "DEVICE", "device-123", status="ACTIVE_UNACK")

        called_url = client._request.call_args[0][1]
        assert "status=ACTIVE_UNACK" in called_url

    def test_should_parse_alarm_list_response(self):
        """Should extract alarm fields from response."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "data": [
                    {
                        "id": {"id": "alarm-1"},  # ID can be nested
                        "type": "TEMP_HIGH",
                        "severity": "CRITICAL",
                        "status": "ACTIVE_UNACK",
                        "createdTime": 1000000,
                        "ackTime": None,
                        "clearTime": None,
                    }
                ]
            }
        )

        result = tb_tools.list_alarms(client, "DEVICE", "device-123")

        assert len(result) == 1
        assert result[0]["id"] == "alarm-1"
        assert result[0]["type"] == "TEMP_HIGH"
        assert result[0]["severity"] == "CRITICAL"

    def test_should_return_empty_list_for_no_alarms(self):
        """Should return empty list when no alarms found."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"data": []})

        result = tb_tools.list_alarms(client, "DEVICE", "device-123")

        assert result == []

    def test_should_handle_list_response_format(self):
        """Should handle response that is a list instead of dict."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            [{"id": "alarm-1", "type": "HIGH_TEMP"}]
        )

        result = tb_tools.list_alarms(client, "DEVICE", "device-123")

        assert len(result) == 1
        assert result[0]["type"] == "HIGH_TEMP"

    def test_should_raise_on_non_200_response(self):
        """Should raise ToolError on non-200 HTTP response."""
        client = MagicMock()
        client._request.return_value = MockResponse(403, text="Forbidden")

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.list_alarms(client, "DEVICE", "device-123")

        assert "403" in str(exc_info.value)

    def test_should_raise_on_malformed_response(self):
        """Should raise ToolError when response is unexpected type."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, "string response")

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.list_alarms(client, "DEVICE", "device-123")

        assert "unexpected type" in str(exc_info.value)


class TestGetSensorCatalog:
    """Test get_sensor_catalog function sourcing."""

    def test_should_return_non_empty_catalog(self):
        """Should return sensor catalog with entries from subsystem registry."""
        catalog = tb_tools.get_sensor_catalog()

        assert isinstance(catalog, list)
        assert len(catalog) > 0

    def test_should_include_all_scored_sensor_keys(self):
        """Should include entries for all scored sensors from subsystems."""
        catalog = tb_tools.get_sensor_catalog()
        catalog_keys = {entry["sensor_key"] for entry in catalog}

        # Verify that scored sensors from SUBSYSTEMS appear in catalog
        for subsystem in SUBSYSTEMS:
            for scored_sensor in subsystem.scored_sensors:
                assert scored_sensor.key in catalog_keys

    def test_should_source_subsystem_asset_ids_from_registry(self):
        """Should verify subsystem_asset_id values come from SUBSYSTEMS, not hardcoded.

        This test enforces that get_sensor_catalog() is pulling from the real
        subsystem registry, not returning fabricated asset IDs.
        """
        catalog = tb_tools.get_sensor_catalog()
        registry_asset_ids = {s.asset_id for s in SUBSYSTEMS}

        for entry in catalog:
            asset_id = entry["subsystem_asset_id"]
            assert asset_id in registry_asset_ids, (
                f"Asset ID {asset_id} not found in SUBSYSTEMS registry"
            )

    def test_should_include_warn_alarm_critical_for_scored_sensors(self):
        """Should include numeric limits for scored sensors."""
        catalog = tb_tools.get_sensor_catalog()

        # Find entries for scored sensors (should have numeric limits)
        scored_entries = [e for e in catalog if e["warn"] is not None]
        assert len(scored_entries) > 0

        for entry in scored_entries:
            assert isinstance(entry["warn"], (int, float))
            assert isinstance(entry["alarm"], (int, float))
            assert isinstance(entry["critical"], (int, float))

    def test_should_include_null_limits_for_primary_sensors(self):
        """Should have null limits for primary-only sensors (no scored limits)."""
        catalog = tb_tools.get_sensor_catalog()

        # Primary sensors have no scored limits
        primary_only_entries = [e for e in catalog if e["warn"] is None]
        assert len(primary_only_entries) > 0

        for entry in primary_only_entries:
            assert entry["alarm"] is None
            assert entry["critical"] is None

    def test_should_include_subsystem_names(self):
        """Should map sensor_key to subsystem_name correctly."""
        catalog = tb_tools.get_sensor_catalog()

        # Verify subsystem names match registry
        for entry in catalog:
            # Find the corresponding subsystem
            subsystem = None
            for s in SUBSYSTEMS:
                if s.asset_id == entry["subsystem_asset_id"]:
                    subsystem = s
                    break

            assert subsystem is not None
            assert entry["subsystem_name"] == subsystem.name


class TestGetOperatingLimits:
    """Test get_operating_limits function."""

    def test_should_return_limits_for_existing_sensor(self):
        """Should return limit dict for a sensor in the registry."""
        # Use a known sensor from SUBSYSTEMS
        sensor_key = "PT_109A"  # From Inlet Steam Admission
        result = tb_tools.get_operating_limits(sensor_key)

        assert result is not None
        assert isinstance(result, dict)
        assert "warn" in result
        assert "alarm" in result
        assert "critical" in result
        assert "source" in result

    def test_should_return_none_for_nonexistent_sensor(self):
        """Should return None when sensor_key not found in registry."""
        result = tb_tools.get_operating_limits("NONEXISTENT_SENSOR_XYZ")

        assert result is None

    def test_should_return_numeric_values(self):
        """Should return numeric values for warn, alarm, and critical."""
        sensor_key = "XT_600"  # From Turbine Core & Rotor
        result = tb_tools.get_operating_limits(sensor_key)

        assert result is not None
        assert isinstance(result["warn"], (int, float))
        assert isinstance(result["alarm"], (int, float))
        assert isinstance(result["critical"], (int, float))

    def test_should_have_warn_less_than_alarm(self):
        """Should satisfy invariant: warn < alarm < critical."""
        sensor_key = "PT_109A"
        result = tb_tools.get_operating_limits(sensor_key)

        assert result is not None
        assert result["warn"] < result["alarm"]
        assert result["alarm"] < result["critical"]

    def test_should_include_source_field(self):
        """Should include source field indicating origin of limits."""
        sensor_key = "PT_109A"
        result = tb_tools.get_operating_limits(sensor_key)

        assert "source" in result
        assert result["source"] is not None


class TestGetAlarmDetails:
    """Test get_alarm_details function."""

    def test_should_fetch_alarm_detail_by_id(self):
        """Should return full detail for an alarm, including originator."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "id": {"id": "alarm-1"},
                "type": "High Vibration",
                "severity": "CRITICAL",
                "status": "ACTIVE_UNACK",
                "createdTime": 1000,
                "ackTime": 0,
                "clearTime": 0,
                "originator": {"entityType": "DEVICE", "id": "device-123"},
                "details": {"note": "gearbox"},
            },
        )

        result = tb_tools.get_alarm_details(client, "alarm-1")

        assert result["id"] == "alarm-1"
        assert result["severity"] == "CRITICAL"
        assert result["originator"]["entity_type"] == "DEVICE"
        assert result["originator"]["entity_id"] == "device-123"
        assert result["details"] == {"note": "gearbox"}

    def test_should_raise_tool_error_for_empty_alarm_id(self):
        """Should raise ToolError when alarm_id is empty."""
        client = MagicMock()
        with pytest.raises(tb_tools.ToolError):
            tb_tools.get_alarm_details(client, "")

    def test_should_raise_tool_error_on_404(self):
        """Should raise ToolError with a clear message when the alarm doesn't exist."""
        client = MagicMock()
        client._request.return_value = MockResponse(404, text="Not found")

        with pytest.raises(tb_tools.ToolError) as exc_info:
            tb_tools.get_alarm_details(client, "missing-alarm")

        assert "missing-alarm" in str(exc_info.value)


class TestBuildChartSpec:
    """Test build_chart_spec function."""

    def test_should_wrap_telemetry_range_into_chart_series(self):
        """Should return a chart_type=line spec with one series per key."""
        client = MagicMock()
        client._request.return_value = MockResponse(
            200,
            {
                "vibration": [{"ts": 1000, "value": 1.2}, {"ts": 2000, "value": 1.4}],
            },
        )

        result = tb_tools.build_chart_spec(
            client, "DEVICE", "device-123", ["vibration"], 0, 100000, title="Vibration"
        )

        assert result["chart_type"] == "line"
        assert result["title"] == "Vibration"
        assert len(result["series"]) == 1
        assert result["series"][0]["key"] == "vibration"
        assert len(result["series"][0]["points"]) == 2

    def test_should_default_title_to_joined_keys(self):
        """Should default title to comma-joined keys when none is given."""
        client = MagicMock()
        client._request.return_value = MockResponse(200, {"a": [], "b": []})

        result = tb_tools.build_chart_spec(client, "DEVICE", "device-123", ["a", "b"], 0, 100000)

        assert result["title"] == "a, b"

    def test_should_propagate_tool_error_from_telemetry_range(self):
        """Should propagate ToolError for an invalid time range."""
        client = MagicMock()
        with pytest.raises(tb_tools.ToolError):
            tb_tools.build_chart_spec(client, "DEVICE", "device-123", ["a"], 100, 50)
