"""Wrapper around OpenAI SDK for local vLLM OpenAI-compatible server streaming.

Handles streaming chat completion requests, fragments accumulation for function tool
calling schemas, and connection error translation.

Exported Classes:
    ModelGatewayError: Raised when vLLM connectivity fails or payload is malformed.

Exported Functions:
    stream_chat_completion: Streams chat completion tokens and intact tool call events.
"""

from __future__ import annotations

import logging
import os
from typing import Iterator

try:
    from openai import OpenAI, APIConnectionError, RateLimitError
except ImportError:
    raise ImportError("openai library not found. Install with: pip install openai")

logger = logging.getLogger(__name__)


class ModelGatewayError(Exception):
    """Raised when vLLM connection fails or response payload is malformed."""
    pass



def stream_chat_completion(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> Iterator[dict]:
    """Stream a chat completion from vLLM, yielding structured events.

    A tool call's name and JSON arguments arrive fragmented across many stream
    chunks (indexed by the API, not necessarily one fragment per tool call).
    This function accumulates those fragments internally and only emits a
    single, complete "tool_calls" event once the stream ends — callers never
    see partial/invalid JSON.

    Args:
        messages: OpenAI-format message list [{"role": "...", "content": "..."}]
        tools: Optional list of tool schemas in OpenAI function-calling format

    Yields:
        {"type": "content", "text": str} for each text delta, and at most one
        {"type": "tool_calls", "tool_calls": [{"id", "name", "arguments"}, ...]}
        event after the stream completes, if the model requested tool calls.

    Raises:
        ModelGatewayError: on connection failure or invalid response
    """
    vllm_base_url = os.environ.get("VLLM_BASE_URL", "http://vllm:8000/v1")
    vllm_api_key = os.environ.get("VLLM_API_KEY")
    vllm_model = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

    if not vllm_api_key:
        raise ModelGatewayError(
            "VLLM_API_KEY environment variable is not set. "
            "Provide a valid API key for vLLM authentication."
        )

    try:
        client = OpenAI(api_key=vllm_api_key, base_url=vllm_base_url)

        # Build request kwargs
        #
        # max_tokens is generous (6144) because hybrid-reasoning models (e.g.
        # Qwen3) spend a large, variable chunk of the budget on an internal
        # <think>...</think> block before ever emitting a tool call or an
        # answer. A tight budget here risks truncating mid-thought, which
        # yields neither a tool call nor visible content — see the
        # finish_reason=="length" handling in orchestrator.py.
        request_kwargs: dict = {
            "model": vllm_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 6144,
        }

        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        logger.debug(
            f"Calling vLLM at {vllm_base_url} with model={vllm_model}, "
            f"num_messages={len(messages)}, tools={len(tools) if tools else 0}"
        )

        # Accumulate tool-call fragments by their stream index until the
        # response completes; a fragment may carry only part of the name
        # or only part of the arguments JSON string.
        tool_calls_acc: dict[int, dict] = {}
        finish_reason: str | None = None

        with client.chat.completions.create(**request_kwargs) as response:
            for chunk in response:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                if delta.content:
                    yield {"type": "content", "text": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        entry = tool_calls_acc.setdefault(
                            tc.index, {"id": None, "name": None, "arguments": ""}
                        )
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function and tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            entry["arguments"] += tc.function.arguments

        if tool_calls_acc:
            ordered = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            for tc in ordered:
                if not tc["arguments"]:
                    tc["arguments"] = "{}"
            yield {"type": "tool_calls", "tool_calls": ordered}

        # Lets callers detect a response cut short by the token budget (most
        # often a hybrid-reasoning model still mid <think> block) so they can
        # avoid silently returning nothing to the user.
        yield {"type": "finish", "finish_reason": finish_reason}

    except APIConnectionError as e:
        raise ModelGatewayError(
            f"Failed to connect to vLLM at {vllm_base_url}: {e}. "
            f"Verify vLLM container is running and reachable."
        ) from e
    except RateLimitError as e:
        raise ModelGatewayError(f"vLLM rate limit exceeded: {e}") from e
    except Exception as e:
        raise ModelGatewayError(f"vLLM request failed: {e}") from e
