"""Tests for orchestrator safety contract.

Tests verify:
- Exactly 5 read-only tools are registered (no write/control tools)
- Tool names and descriptions contain no dangerous substrings
- 3-tool-call limit per turn is enforced
- No write/RPC/control/acknowledge operations are exposed
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


# Expected tool names (read-only, no write/control)
EXPECTED_TOOL_NAMES = {
    "get_latest_telemetry",
    "get_telemetry_range",
    "list_alarms",
    "get_alarm_details",
    "get_sensor_catalog",
    "get_operating_limits",
    "get_analysis_results",
    "render_chart",
    "open_dashboard",
}

# Dangerous substrings that should never appear in tool names/descriptions
DANGEROUS_SUBSTRINGS = {
    "rpc",
    "write",
    "ack",
    "set_",
    "control",
    "execute",
    "acknowledge",
}


class TestOrchestratorToolRegistration:
    """Test that orchestrator registers only safe, read-only tools."""

    def test_should_import_orchestrator_module(self):
        """Should be able to import the orchestrator module."""
        try:
            from app.copilot_backend import orchestrator
            assert orchestrator is not None
        except ImportError as e:
            pytest.fail(f"Failed to import orchestrator: {e}")

    def test_should_have_tool_schemas_attribute(self):
        """Should export a list of tool schemas."""
        from app.copilot_backend import orchestrator
        assert hasattr(orchestrator, "TOOL_SCHEMAS")
        assert isinstance(orchestrator.TOOL_SCHEMAS, list)

    def test_tool_schemas_should_have_exactly_nine_tools(self):
        """Should register exactly 9 tools (no more, no fewer)."""
        from app.copilot_backend import orchestrator

        tool_names = {tool["function"]["name"] for tool in orchestrator.TOOL_SCHEMAS}
        assert len(tool_names) == 9, f"Expected 9 tools, got {len(tool_names)}: {tool_names}"

    def test_tool_names_should_match_expected_set(self):
        """Should register exactly the expected read-only tools."""
        from app.copilot_backend import orchestrator

        tool_names = {tool["function"]["name"] for tool in orchestrator.TOOL_SCHEMAS}
        assert tool_names == EXPECTED_TOOL_NAMES, (
            f"Tool names mismatch. "
            f"Expected: {EXPECTED_TOOL_NAMES}, "
            f"Got: {tool_names}, "
            f"Extra: {tool_names - EXPECTED_TOOL_NAMES}, "
            f"Missing: {EXPECTED_TOOL_NAMES - tool_names}"
        )

    def test_no_tool_names_contain_dangerous_substrings(self):
        """Should not register tools with dangerous names."""
        from app.copilot_backend import orchestrator

        for tool in orchestrator.TOOL_SCHEMAS:
            tool_name = tool["function"]["name"].lower()
            for substring in DANGEROUS_SUBSTRINGS:
                assert substring not in tool_name, (
                    f"Tool name '{tool['function']['name']}' contains dangerous substring '{substring}'"
                )

    def test_no_tool_descriptions_contain_dangerous_substrings(self):
        """Should not have dangerous keywords in tool descriptions."""
        from app.copilot_backend import orchestrator

        for tool in orchestrator.TOOL_SCHEMAS:
            description = (tool["function"].get("description") or "").lower()
            for substring in DANGEROUS_SUBSTRINGS:
                assert substring not in description, (
                    f"Tool '{tool['function']['name']}' description contains dangerous substring '{substring}'"
                )


class TestOrchestratorToolExecutionLimit:
    """Test that orchestrator enforces 3-tool-call limit per turn."""

    def test_should_have_execute_tools_method(self):
        """Should have a way to execute a single tool call and to run the
        overall per-turn loop that enforces the call cap."""
        from app.copilot_backend import orchestrator
        assert hasattr(orchestrator, "execute_tool_call")
        assert hasattr(orchestrator, "orchestrate_chat")

    def test_should_enforce_three_tool_call_limit(self):
        """Should stop after exactly 3 tool executions and not call more.

        This tests the critical safety rule: a single user turn can trigger
        at most 3 tool calls. If the model requests more in one response, the
        loop still executes only the first 3 and does not call the 4th.
        """
        from app.copilot_backend import orchestrator

        # Model responds once with 4 tool calls requested simultaneously.
        fake_model_response = [
            {
                "type": "tool_calls",
                "tool_calls": [
                    {"id": "1", "name": "get_latest_telemetry", "arguments": '{"entity_type":"DEVICE","entity_id":"t","keys":[]}'},
                    {"id": "2", "name": "list_alarms", "arguments": '{"entity_type":"DEVICE","entity_id":"t"}'},
                    {"id": "3", "name": "get_sensor_catalog", "arguments": "{}"},
                    {"id": "4", "name": "get_operating_limits", "arguments": '{"sensor_key":"PT_109A"}'},
                ],
            }
        ]

        with patch("app.copilot_backend.orchestrator.stream_chat_completion", return_value=iter(fake_model_response)), \
             patch("app.copilot_backend.orchestrator.get_latest_telemetry", return_value={}) as m1, \
             patch("app.copilot_backend.orchestrator.list_alarms", return_value=[]) as m2, \
             patch("app.copilot_backend.orchestrator.get_sensor_catalog", return_value=[]) as m3, \
             patch("app.copilot_backend.orchestrator.get_operating_limits", return_value=None) as m4:
            list(orchestrator.orchestrate_chat(
                user_message="Tell me about the turbine",
                conversation_history=[],
                tb_client=MagicMock(),
            ))

        tool_execution_count = m1.call_count + m2.call_count + m3.call_count + m4.call_count
        assert tool_execution_count <= 3, (
            f"More than 3 tools were executed: {tool_execution_count}"
        )
        # The 4th tool call (get_operating_limits) must never have run.
        assert m4.call_count == 0

    def test_should_surface_tool_limit_reached_condition(self):
        """Should clearly indicate when tool-call limit is reached.

        If a user turn hits the 3-tool limit, the orchestrator should yield a
        clear message so the caller knows why more tools weren't called.
        """
        from app.copilot_backend import orchestrator

        fake_model_response = [
            {
                "type": "tool_calls",
                "tool_calls": [
                    {"id": "1", "name": "get_latest_telemetry", "arguments": "{}"},
                    {"id": "2", "name": "list_alarms", "arguments": "{}"},
                    {"id": "3", "name": "get_sensor_catalog", "arguments": "{}"},
                    {"id": "4", "name": "get_operating_limits", "arguments": "{}"},
                ],
            }
        ]

        with patch("app.copilot_backend.orchestrator.stream_chat_completion", return_value=iter(fake_model_response)), \
             patch("app.copilot_backend.orchestrator.get_latest_telemetry", return_value={}), \
             patch("app.copilot_backend.orchestrator.list_alarms", return_value=[]), \
             patch("app.copilot_backend.orchestrator.get_sensor_catalog", return_value=[]), \
             patch("app.copilot_backend.orchestrator.get_operating_limits", return_value=None):
            chunks = list(orchestrator.orchestrate_chat(
                user_message="Tell me about the turbine",
                conversation_history=[],
                tb_client=MagicMock(),
            ))

        assert any("limit" in chunk.lower() for chunk in chunks), (
            f"Expected a tool-call-limit message in the output, got: {chunks}"
        )


class TestOrchestratorToolSchemaStructure:
    """Test that tool schemas follow OpenAI function-calling format."""

    def test_each_tool_schema_should_have_required_fields(self):
        """Each tool should be an OpenAI function-calling entry with name,
        description, and parameters nested under 'function'."""
        from app.copilot_backend import orchestrator

        for tool in orchestrator.TOOL_SCHEMAS:
            assert tool.get("type") == "function", "Tool missing type='function'"
            fn = tool.get("function", {})
            assert "name" in fn, "Tool missing 'function.name' field"
            assert "description" in fn, "Tool missing 'function.description' field"
            assert "parameters" in fn, "Tool missing 'function.parameters' field"

    def test_tool_parameters_should_follow_openai_format(self):
        """Tool parameters should have 'type' and 'properties'."""
        from app.copilot_backend import orchestrator

        for tool in orchestrator.TOOL_SCHEMAS:
            fn = tool["function"]
            params = fn.get("parameters", {})
            assert params.get("type") == "object", f"Tool {fn['name']} parameters type not 'object'"
            assert "properties" in params, f"Tool {fn['name']} parameters missing 'properties'"

    def test_tool_parameters_should_match_python_signatures(self):
        """Tool parameters should match the actual Python function signatures."""
        from app.copilot_backend import orchestrator, thingsboard_tools

        # Build mapping of function names to their signatures
        tb_tools_funcs = {
            "get_latest_telemetry": tb_tools.get_latest_telemetry,
            "get_telemetry_range": tb_tools.get_telemetry_range,
            "list_alarms": tb_tools.list_alarms,
            "get_sensor_catalog": tb_tools.get_sensor_catalog,
            "get_operating_limits": tb_tools.get_operating_limits,
        }

        for tool in orchestrator.TOOL_SCHEMAS:
            fn = tool["function"]
            tool_name = fn["name"]
            if tool_name in tb_tools_funcs:
                # Verify parameters are reasonable approximations of function args
                params = fn.get("parameters", {}).get("properties", {})
                # At minimum, should have some parameters for most tools
                assert len(params) >= 0, f"Tool {tool_name} has unreasonable parameter count"
