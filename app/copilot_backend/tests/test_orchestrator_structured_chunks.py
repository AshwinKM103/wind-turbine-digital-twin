"""Tests that render_chart/open_dashboard tool calls surface as structured
dict chunks in the orchestrator's output stream, not just prose describing
them — the widget needs the actual spec/action object to render a chart or
a nav button, not the model's paraphrase of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.copilot_backend import orchestrator


def _fake_stream(tool_calls, final_text="Here you go."):
    """Simulates stream_chat_completion: one turn requesting tool_calls, then
    a second turn (synthesis) emitting final_text."""
    calls = [
        [{"type": "tool_calls", "tool_calls": tool_calls}, {"type": "finish", "finish_reason": "tool_calls"}],
        [{"type": "content", "text": final_text}, {"type": "finish", "finish_reason": "stop"}],
    ]

    def _gen(*args, **kwargs):
        return iter(calls.pop(0))

    return _gen


class TestRenderChartStructuredChunk:
    def test_render_chart_result_emits_a_chart_chunk(self):
        tool_calls = [
            {
                "id": "1",
                "name": "render_chart",
                "arguments": json.dumps(
                    {"keys": ["PT_109A"], "start_ts": 0, "end_ts": 100000}
                ),
            }
        ]

        fake_spec = {
            "chart_type": "line",
            "title": "PT_109A",
            "series": [{"key": "PT_109A", "points": [{"ts": 1, "value": 1.0}]}],
            "truncated": False,
        }

        with patch(
            "app.copilot_backend.orchestrator.stream_chat_completion", side_effect=_fake_stream(tool_calls)
        ), patch(
            "app.copilot_backend.orchestrator.build_chart_spec", return_value=fake_spec
        ):
            chunks = list(
                orchestrator.orchestrate_chat(
                    user_message="Show me a chart of PT_109A",
                    conversation_history=[],
                    tb_client=MagicMock(),
                    resolved_entity={"entity_type": "DEVICE", "entity_id": "d1", "device_name": "boreas"},
                )
            )

        chart_chunks = [c for c in chunks if isinstance(c, dict) and c.get("type") == "chart"]
        assert len(chart_chunks) == 1
        assert chart_chunks[0]["spec"] == fake_spec

        # Plain text chunks (the synthesis) must still come through as strings.
        # _ThinkTagFilter may split a single content event across multiple
        # yielded chunks (it holds back a tail that could start a <think>
        # tag), so assert on the joined text rather than a single chunk.
        text_chunks = [c for c in chunks if isinstance(c, str)]
        assert "Here you go" in "".join(text_chunks)


class TestOpenDashboardStructuredChunk:
    def test_open_dashboard_result_emits_a_ui_action_chunk(self):
        tool_calls = [
            {
                "id": "1",
                "name": "open_dashboard",
                "arguments": json.dumps({"dashboard_key": "scada_mimic"}),
            }
        ]

        fake_action = {
            "action": "OPEN_DASHBOARD",
            "dashboardId": "c5704b70-b04c-11f1-9bfc-5d2538928d0b",
            "dashboardKey": "scada_mimic",
            "label": "Open Turbine Process SCADA Mimic",
        }

        with patch(
            "app.copilot_backend.orchestrator.stream_chat_completion", side_effect=_fake_stream(tool_calls)
        ), patch(
            "app.copilot_backend.orchestrator.build_open_dashboard_action", return_value=fake_action
        ):
            chunks = list(
                orchestrator.orchestrate_chat(
                    user_message="Take me to the SCADA view",
                    conversation_history=[],
                    tb_client=MagicMock(),
                    resolved_entity={"entity_type": "DEVICE", "entity_id": "d1", "device_name": "boreas"},
                )
            )

        action_chunks = [c for c in chunks if isinstance(c, dict) and c.get("type") == "ui_action"]
        assert len(action_chunks) == 1
        assert action_chunks[0]["action"] == fake_action

    def test_unknown_dashboard_key_never_reaches_the_widget_as_an_action(self):
        tool_calls = [
            {
                "id": "1",
                "name": "open_dashboard",
                "arguments": json.dumps({"dashboard_key": "not_a_real_dashboard"}),
            }
        ]

        with patch(
            "app.copilot_backend.orchestrator.stream_chat_completion", side_effect=_fake_stream(tool_calls)
        ):
            chunks = list(
                orchestrator.orchestrate_chat(
                    user_message="Take me to nowhere",
                    conversation_history=[],
                    tb_client=MagicMock(),
                    resolved_entity={"entity_type": "DEVICE", "entity_id": "d1", "device_name": "boreas"},
                )
            )

        action_chunks = [c for c in chunks if isinstance(c, dict) and c.get("type") == "ui_action"]
        assert action_chunks == []
