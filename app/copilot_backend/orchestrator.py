"""Deterministic chat orchestrator with tool calling and safety boundaries."""

from __future__ import annotations

import json
import logging
from typing import Iterator

try:
    from app.copilot_backend.model_gateway import stream_chat_completion, ModelGatewayError
except ImportError:
    from model_gateway import stream_chat_completion, ModelGatewayError

# Import tb_tools functions; fail fast if unavailable
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
    try:
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
    except ImportError as e:
        raise RuntimeError(
            "tb_tools.py not available. Ensure app/copilot_backend/tb_tools.py "
            "is present and implements the required contract (get_latest_telemetry, etc.)"
        ) from e

try:
    from app.copilot_backend.anomaly_service import get_analysis_results, AnomalyServiceError
except ImportError:
    from anomaly_service import get_analysis_results, AnomalyServiceError

try:
    from app.copilot_backend.dashboard_actions import build_open_dashboard_action, DashboardActionError, DASHBOARD_ALLOWLIST
except ImportError:
    from dashboard_actions import build_open_dashboard_action, DashboardActionError, DASHBOARD_ALLOWLIST

logger = logging.getLogger(__name__)

# Maximum tool calls per single user turn
MAX_TOOL_CALLS_PER_TURN = 3

# Generic, user-safe messages. Full exception detail is always logged
# server-side (logger.error) but never streamed to the chat UI: raw
# exception text can carry internal hostnames, ports, or provider wire
# format (security rule: never expose stack traces/internals to users).
GENERIC_MODEL_ERROR = (
    "I'm having trouble reaching the language model right now. Please try again shortly."
)
GENERIC_SYNTHESIS_ERROR = (
    "\nI retrieved the data but had trouble summarizing it. Please try asking again."
)


class _ThinkTagFilter:
    """Strips <think>...</think> reasoning blocks from a streamed text feed.

    Thinking-hybrid models (e.g. Qwen3) emit raw chain-of-thought wrapped in
    <think> tags as ordinary content deltas. Left unfiltered, that internal
    reasoning is streamed straight into the user-facing chat. This filter is
    stateful so it can strip tags even when the stream splits them across
    multiple chunks.
    """

    START = "<think>"
    END = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        visible = []
        while True:
            if not self._in_think:
                idx = self._buffer.find(self.START)
                if idx == -1:
                    # Hold back a tail that could be the start of a split tag.
                    safe_len = len(self._buffer) - (len(self.START) - 1)
                    if safe_len > 0:
                        visible.append(self._buffer[:safe_len])
                        self._buffer = self._buffer[safe_len:]
                    break
                visible.append(self._buffer[:idx])
                self._buffer = self._buffer[idx + len(self.START):]
                self._in_think = True
            else:
                idx = self._buffer.find(self.END)
                if idx == -1:
                    safe_len = len(self._buffer) - (len(self.END) - 1)
                    if safe_len > 0:
                        self._buffer = self._buffer[safe_len:]
                    break
                self._buffer = self._buffer[idx + len(self.END):]
                self._in_think = False
        return "".join(visible)

    def flush(self) -> str:
        """Call once the stream ends to release any safely-held trailing text."""
        if self._in_think:
            self._buffer = ""
            return ""
        remainder = self._buffer
        self._buffer = ""
        return remainder

# System prompt emphasizing read-only, audit, and safety boundaries
SYSTEM_PROMPT = """You are a READ-ONLY turbine diagnostic assistant for a wind farm digital twin.

CRITICAL CONSTRAINTS:
1. You can ONLY observe and explain turbine data. You CANNOT control equipment, acknowledge alarms, or modify any state.
2. Every fact you state must cite its source: the tool call that produced it (e.g., "Based on get_latest_telemetry for Boreas...").
3. If data is stale or missing, explicitly state this. Do not invent or assume data.
4. If a user asks you to control equipment, acknowledge an alarm, modify settings, or write data to ThingsBoard, refuse clearly and explain why.
5. Keep responses concise. Focus on what the data shows, not narrative speculation.

6. The current turbine's ThingsBoard device identity is resolved and injected by the server (see CURRENT TURBINE CONTEXT below, if present). Never guess, invent, or ask the user for an entity ID — telemetry and alarm tools apply the resolved device automatically.

AVAILABLE TOOLS:
- get_latest_telemetry: fetch current sensor readings from the current turbine
- get_telemetry_range: fetch historical sensor data over a time window with optional aggregation
- list_alarms: fetch active or historical alarms for the current turbine
- get_alarm_details: fetch full detail for one specific alarm by ID (originator, propagation)
- get_sensor_catalog: list all available sensors and their metadata
- get_operating_limits: fetch min/max safe operating ranges for a sensor
- get_analysis_results: fetch anomaly-detection results from the dedicated analytics model
  (a separate Isolation Forest model — this is NOT you reasoning over raw numbers; it is a
  versioned evidence object with a score and contributing sensors. Explain it, don't
  relabel it as a confirmed mechanical fault.)
- render_chart: return a bounded chart of one or more sensors over a time range for the
  widget to draw. Use for "show me a chart of X" style requests.
- open_dashboard: return a navigation intent to one of the fixed, allowlisted dashboards
  (never a raw URL). This is a UI action, not equipment control.

USE THESE TOOLS to answer questions about:
- Current turbine status, power output, vibration, temperature
- Historical trends and anomalies
- Active and resolved alarms, including a specific alarm's originator detail
- Sensor specifications and operating windows
- Whether a subsystem's current readings look statistically anomalous

REFUSE REQUESTS to:
- Write or modify any device attributes or settings
- Acknowledge or suppress alarms
- Control turbine behavior (ramp, shutdown, etc.)
- Call any API not in the tool list above
- Access other turbines' data without explicit user context

After using tools, synthesize their results into a clear answer. Always cite tool sources."""


def build_tool_schemas() -> list[dict]:
    """Build OpenAI function-calling schema for the 5 read-only tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_latest_telemetry",
                "description": (
                    "Fetch the most recent sensor readings from the current turbine. "
                    "The device is resolved automatically from dashboard context; do not supply an entity ID."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Sensor/metric keys to fetch (e.g., ['power_output', 'vibration', 'temperature'])",
                        },
                    },
                    "required": ["keys"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_telemetry_range",
                "description": (
                    "Fetch historical sensor data for the current turbine over a time range, with optional "
                    "aggregation. The device is resolved automatically from dashboard context; do not supply an entity ID."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Sensor keys to fetch.",
                        },
                        "start_ts": {
                            "type": "integer",
                            "description": "Start timestamp in milliseconds (Unix epoch).",
                        },
                        "end_ts": {
                            "type": "integer",
                            "description": "End timestamp in milliseconds (Unix epoch).",
                        },
                        "interval_ms": {
                            "type": "integer",
                            "description": "Aggregation interval in milliseconds (0 = no aggregation). Default: 0",
                        },
                        "max_points": {
                            "type": "integer",
                            "description": "Maximum number of points to return. Default: 500",
                        },
                    },
                    "required": ["keys", "start_ts", "end_ts"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_alarms",
                "description": (
                    "Fetch alarms for the current turbine, optionally filtered by status. "
                    "The device is resolved automatically from dashboard context; do not supply an entity ID."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": (
                                "Filter by exact ThingsBoard alarm status enum: 'ACTIVE_UNACK', "
                                "'ACTIVE_ACK', 'CLEARED_UNACK', or 'CLEARED_ACK'. Omit for all statuses. "
                                "Other values (e.g. 'ACTIVE', 'ANY') are rejected by ThingsBoard."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of alarms to return. Default: 50",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_sensor_catalog",
                "description": "List all available sensors and their metadata (names, units, types).",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_operating_limits",
                "description": "Fetch min/max safe operating ranges for a specific sensor.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sensor_key": {
                            "type": "string",
                            "description": "Sensor key (e.g., 'power_output', 'vibration', 'temperature').",
                        },
                    },
                    "required": ["sensor_key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_alarm_details",
                "description": (
                    "Fetch full detail for one specific alarm by ID (originator entity, "
                    "propagation), for follow-up questions after list_alarms."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "alarm_id": {
                            "type": "string",
                            "description": "Alarm UUID, normally taken from a prior list_alarms result.",
                        },
                    },
                    "required": ["alarm_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_analysis_results",
                "description": (
                    "Fetch anomaly-detection results from the dedicated analytics model for "
                    "the current turbine. Returns a versioned evidence object (score, "
                    "severity, contributing sensors), not a raw data dump. Omit component_id "
                    "to scan all subsystems for the most anomalous ones."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "component_id": {
                            "type": "string",
                            "description": (
                                "Subsystem name to score (e.g. 'Gearbox', 'Dynamometer'). "
                                "Omit to scan every subsystem and return the most anomalous."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "render_chart",
                "description": (
                    "Return a bounded chart of one or more sensors over a time range for the "
                    "chat widget to draw inline. Use when the user asks to see/plot/chart data, "
                    "or to compare two sensors visually."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Sensor keys to chart.",
                        },
                        "start_ts": {
                            "type": "integer",
                            "description": "Start timestamp in milliseconds (Unix epoch).",
                        },
                        "end_ts": {
                            "type": "integer",
                            "description": "End timestamp in milliseconds (Unix epoch).",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional chart title.",
                        },
                    },
                    "required": ["keys", "start_ts", "end_ts"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open_dashboard",
                "description": (
                    "Return a navigation intent to one of the fixed dashboards, for the widget "
                    "to offer as a button. This is a UI navigation action on the dashboard "
                    "itself, never a command to the physical turbine. "
                    f"Allowlisted dashboard keys: {', '.join(DASHBOARD_ALLOWLIST.keys())}."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dashboard_key": {
                            "type": "string",
                            "enum": list(DASHBOARD_ALLOWLIST.keys()),
                            "description": "Which dashboard to navigate to.",
                        },
                    },
                    "required": ["dashboard_key"],
                },
            },
        },
    ]


# Module-level snapshot for introspection/tests (e.g. asserting exactly 5
# read-only tools are registered, with no dangerous names/descriptions).
# The live request path always calls build_tool_schemas() directly.
TOOL_SCHEMAS: list[dict] = build_tool_schemas()


try:
    from app.copilot_backend.tool_executor import ToolExecutor
except ImportError:
    from tool_executor import ToolExecutor

_tool_executor = ToolExecutor()


def execute_tool_call(
    tool_name: str,
    tool_args_json: str,
    tb_client: object,  # ThingsboardClient instance
    resolved_entity: dict | None = None,
) -> str:
    """Execute a single tool call and return the result as a string."""
    return _tool_executor.execute_tool(
        tool_name=tool_name,
        tool_args_json=tool_args_json,
        tb_client=tb_client,
        resolved_entity=resolved_entity,
    )


def orchestrate_chat(
    user_message: str,
    conversation_history: list[dict],
    tb_client: object,  # ThingsboardClient instance
    resolved_entity: dict | None = None,
) -> Iterator[str]:
    """Deterministic chat loop: call model, execute tools, synthesize response.

    Args:
        user_message: the latest user input
        conversation_history: list of prior turns [{"role": "...", "content": "..."}]
        tb_client: authenticated ThingsboardClient instance
        resolved_entity: server-verified {"entity_type", "entity_id", "device_name"}
            for the current turbine (see tb_tools.resolve_turbine_device), or None
            if no turbine context is available for this conversation.

    Yields:
        Text chunks of the final natural-language response
    """
    system_content = SYSTEM_PROMPT
    if resolved_entity:
        system_content += (
            "\n\nCURRENT TURBINE CONTEXT (server-verified — do not override):\n"
            f"- device_name: {resolved_entity.get('device_name', 'unknown')}\n"
            "This is the only turbine in scope for this conversation. Telemetry and "
            "alarm tools apply it automatically."
        )

    # Build message list: system prompt + history + user message
    messages = [
        {"role": "system", "content": system_content},
        *conversation_history,
        {"role": "user", "content": user_message},
    ]

    tool_schemas = build_tool_schemas()
    assistant_text = ""
    pending_tool_calls: list[dict] | None = None

    logger.info(
        "Starting orchestrate_chat",
        extra={
            "num_messages": len(messages),
            "num_tools_available": len(tool_schemas),
        },
    )

    # --- First call to model with tools ---
    think_filter = _ThinkTagFilter()
    visible_emitted = False
    finish_reason: str | None = None
    try:
        for event in stream_chat_completion(messages, tools=tool_schemas):
            if event["type"] == "content":
                assistant_text += event["text"]
                visible = think_filter.feed(event["text"])
                if visible:
                    visible_emitted = True
                    yield visible
            elif event["type"] == "tool_calls":
                pending_tool_calls = event["tool_calls"]
            elif event["type"] == "finish":
                finish_reason = event["finish_reason"]
        trailing = think_filter.flush()
        if trailing:
            visible_emitted = True
            yield trailing
    except ModelGatewayError as e:
        logger.error(f"Model gateway error: {e}")
        yield GENERIC_MODEL_ERROR
        return

    if not pending_tool_calls:
        # No tool calls requested. If generation was cut short by the token
        # budget (typical: a hybrid-reasoning model still mid <think> block)
        # and nothing visible ever made it out, the user would otherwise see
        # a silent, empty response with no explanation. Never let that happen.
        if not visible_emitted:
            if finish_reason == "length":
                logger.warning("Model response truncated before producing an answer or tool call")
                yield (
                    "I started analyzing that but ran out of room to finish. "
                    "Could you ask a more specific, narrower question?"
                )
            else:
                logger.info("No tool calls requested by model and no content produced")
                yield "I'm not sure how to answer that. Could you rephrase your question?"
        else:
            logger.info("No tool calls requested by model")
        return

    # --- Enforce the per-turn tool call cap ---
    truncated = len(pending_tool_calls) > MAX_TOOL_CALLS_PER_TURN
    executed_calls = pending_tool_calls[:MAX_TOOL_CALLS_PER_TURN]

    # --- Execute tool calls, building a spec-correct OpenAI message sequence ---
    tool_call_ids = [tc["id"] or f"call_{i}" for i, tc in enumerate(executed_calls)]
    messages.append(
        {
            "role": "assistant",
            "content": assistant_text or None,
            "tool_calls": [
                {
                    "id": tool_call_ids[i],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for i, tc in enumerate(executed_calls)
            ],
        }
    )

    structured_chunks: list[dict] = []
    for i, tc in enumerate(executed_calls):
        logger.info(
            f"Executing tool call #{i + 1}: {tc['name']}",
            extra={"tool_name": tc["name"]},
        )
        result_str = execute_tool_call(tc["name"], tc["arguments"], tb_client, resolved_entity)

        # render_chart/open_dashboard wrap their payload with a "__structured__"
        # marker so the widget can render it directly (a chart, a nav button)
        # instead of the model re-describing it in prose. The model still sees
        # the underlying spec/action (minus the marker) so it can reference it
        # in its synthesis, e.g. "here's the chart you asked for".
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        if isinstance(parsed, dict) and "__structured__" in parsed:
            kind = parsed["__structured__"]
            payload_key = "spec" if kind == "chart" else "action"
            structured_chunks.append({"type": kind, payload_key: parsed[payload_key]})
            result_str = json.dumps(parsed[payload_key])

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_ids[i],
                "content": result_str,
            }
        )

    # Emit structured chunks (charts, nav buttons) before the synthesized
    # text so the widget can render them immediately rather than waiting on
    # the second model call below.
    for chunk in structured_chunks:
        yield chunk

    if truncated:
        limit_msg = f"\n[Tool call limit reached: {MAX_TOOL_CALLS_PER_TURN} max per turn]"
        logger.warning(
            limit_msg,
            extra={
                "tool_calls_requested": len(pending_tool_calls),
                "max_allowed": MAX_TOOL_CALLS_PER_TURN,
            },
        )
        yield limit_msg
        return

    # --- Second call to model for synthesis ---
    synthesis_prompt = (
        "Based on the tool results above, provide a concise, factual answer. "
        "Cite which tool produced each fact."
    )
    messages.append({"role": "user", "content": synthesis_prompt})

    logger.info(
        "Calling model for synthesis",
        extra={"num_tool_results": len(executed_calls)},
    )

    synthesis_filter = _ThinkTagFilter()
    synthesis_visible = False
    synthesis_finish_reason: str | None = None
    try:
        for event in stream_chat_completion(messages, tools=None):
            if event["type"] == "content":
                visible = synthesis_filter.feed(event["text"])
                if visible:
                    synthesis_visible = True
                    yield visible
            elif event["type"] == "finish":
                synthesis_finish_reason = event["finish_reason"]
        trailing = synthesis_filter.flush()
        if trailing:
            synthesis_visible = True
            yield trailing
        if not synthesis_visible:
            # Same silent-truncation hazard as the first call: the tools ran
            # successfully, but the synthesis turn produced nothing the user
            # can see (e.g. cut off mid <think>). Say so instead of nothing.
            logger.warning(
                "Synthesis call produced no visible content",
                extra={"finish_reason": synthesis_finish_reason},
            )
            yield GENERIC_SYNTHESIS_ERROR
    except ModelGatewayError as e:
        logger.error(f"Model gateway error during synthesis: {e}")
        yield GENERIC_SYNTHESIS_ERROR
