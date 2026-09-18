"""Regression tests for model_gateway.stream_chat_completion.

Covers the empty-tool-arguments bug: a zero-argument tool call (e.g.
get_sensor_catalog) streamed an empty string for its `arguments` field.
OpenAI-compatible servers (vLLM/hermes) reject that empty string when it's
echoed back in the next request's tool_calls history ("Expecting value: line
1 column 1 (char 0)"), breaking the synthesis turn. The fix normalizes empty
arguments to "{}", a valid empty JSON object.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.copilot_backend.model_gateway import stream_chat_completion


def _fake_tool_call_chunk(index: int, id_: str | None, name: str | None, arguments: str | None):
    """Builds a fake OpenAI streaming chunk carrying one tool_call delta fragment."""
    tool_call = MagicMock()
    tool_call.index = index
    tool_call.id = id_
    if name is not None or arguments is not None:
        tool_call.function = MagicMock(name=name, arguments=arguments)
        tool_call.function.name = name
        tool_call.function.arguments = arguments
    else:
        tool_call.function = None

    delta = MagicMock()
    delta.content = None
    delta.tool_calls = [tool_call]

    choice = MagicMock()
    choice.delta = delta

    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


class _FakeStreamContext:
    """Mimics the `with client.chat.completions.create(...) as response:` context
    manager, yielding the given chunks when iterated."""

    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return iter(self._chunks)

    def __exit__(self, *args):
        return False


class TestEmptyToolArgumentsNormalization:
    def test_zero_argument_tool_call_gets_empty_object_not_empty_string(self):
        """A tool call whose arguments delta never carries any text (as vLLM
        does for a no-parameter function like get_sensor_catalog) must be
        normalized to '{}', not left as ''."""
        chunks = [
            _fake_tool_call_chunk(0, "call_1", "get_sensor_catalog", None),
        ]

        with patch("app.copilot_backend.model_gateway.OpenAI") as mock_openai_cls, \
             patch.dict("os.environ", {"VLLM_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _FakeStreamContext(chunks)
            mock_openai_cls.return_value = mock_client

            events = list(stream_chat_completion([{"role": "user", "content": "hi"}], tools=[]))

        tool_call_events = [e for e in events if e["type"] == "tool_calls"]
        assert len(tool_call_events) == 1
        assert tool_call_events[0]["tool_calls"][0]["arguments"] == "{}"

    def test_arguments_with_content_are_preserved_unchanged(self):
        """A tool call that does stream argument fragments must not be altered."""
        chunks = [
            _fake_tool_call_chunk(0, "call_1", "get_operating_limits", '{"sensor_key"'),
            _fake_tool_call_chunk(0, None, None, ': "PT_109A"}'),
        ]

        with patch("app.copilot_backend.model_gateway.OpenAI") as mock_openai_cls, \
             patch.dict("os.environ", {"VLLM_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = _FakeStreamContext(chunks)
            mock_openai_cls.return_value = mock_client

            events = list(stream_chat_completion([{"role": "user", "content": "hi"}], tools=[]))

        tool_call_events = [e for e in events if e["type"] == "tool_calls"]
        assert tool_call_events[0]["tool_calls"][0]["arguments"] == '{"sensor_key": "PT_109A"}'
