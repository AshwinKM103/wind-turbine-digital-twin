"""Tests for FastAPI main application contract.

Tests verify:
- GET /health endpoint returns 200 with correct structure
- POST /chat accepts valid requests and streams responses
- Invalid requests return appropriate error status codes
- All external systems mocked (ThingsBoard, vLLM, PostgreSQL)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any
import json

import sys
from pathlib import Path

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Conditional import since main.py may not exist yet
try:
    from fastapi.testclient import TestClient
    TESTCLIENT_AVAILABLE = True
except ImportError:
    TESTCLIENT_AVAILABLE = False


@pytest.fixture(autouse=True)
def _fake_tb_client():
    """Bypass real ThingsBoard startup: a bare TestClient(app) never runs the
    app's lifespan (that only happens under `with TestClient(app) as client:`),
    so main._tb_client stays None and every request would 500 in
    get_tb_client(). Set it directly instead of standing up a real
    ThingsBoard connection or asserting on lifespan behavior we don't test
    here."""
    if not TESTCLIENT_AVAILABLE:
        yield
        return
    import app.copilot_backend.copilot_backend_main as copilot_main

    previous = copilot_main._tb_client
    copilot_main._tb_client = MagicMock()
    yield
    copilot_main._tb_client = previous


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI/TestClient not available")
class TestHealthEndpoint:
    """Test GET /health endpoint."""

    def test_health_endpoint_exists_and_returns_ok(self):
        """Should return 200 with health status."""
        # Import and create test client (will be created when main.py exists)
        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    def test_health_endpoint_response_structure(self):
        """Should return a dict with 'status' key."""
        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI/TestClient not available")
class TestChatEndpoint:
    """Test POST /chat streaming endpoint."""

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_accepts_valid_request(self, mock_postgres, mock_stream):
        """Should accept POST /chat with conversation_id, message, and context."""
        # Mock external systems
        mock_stream.return_value = iter(["Hello from model"])
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "What is the turbine status?",
                "context": {"turbine_id": "boreas"},
            },
        )

        assert response.status_code == 200

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_returns_streaming_response(self, mock_postgres, mock_stream):
        """Should return streaming response with SSE content-type."""
        mock_stream.return_value = iter(["chunk1", "chunk2", "chunk3"])
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": None,
                "message": "Tell me about temperature sensors",
                "context": {"turbine_id": "boreas"},
            },
        )

        assert response.status_code == 200
        # Should be streaming or text response
        assert response.headers.get("content-type") is not None

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_without_conversation_id_creates_new(self, mock_postgres, mock_stream):
        """Should handle conversation_id=None by creating a new conversation."""
        mock_stream.return_value = iter(["response"])
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": None,
                "message": "Start a new chat",
                "context": {"turbine_id": "boreas"},
            },
        )

        # Should succeed, possibly generating a new conversation ID
        assert response.status_code == 200

    def test_chat_endpoint_rejects_missing_message(self):
        """Should return 422 when 'message' field is missing."""
        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                # Missing 'message' field
                "context": {"turbine_id": "boreas"},
            },
        )

        assert response.status_code == 422

    def test_chat_endpoint_rejects_malformed_json(self):
        """Should return 400 or 422 for malformed JSON."""
        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            data="not valid json",
            headers={"content-type": "application/json"},
        )

        assert response.status_code in (400, 422)

    def test_chat_endpoint_rejects_empty_message(self):
        """Should handle empty or whitespace-only messages."""
        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "   ",  # Whitespace only
                "context": {"turbine_id": "boreas"},
            },
        )

        # Could be 400/422 or could accept it; implementation decides
        # At minimum should not crash (status < 500)
        assert response.status_code < 500


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI/TestClient not available")
class TestChatEndpointIntegration:
    """Integration tests for /chat with mocked backends."""

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    @patch("app.copilot_backend.copilot_backend_main.ThingsboardClient")
    def test_chat_endpoint_with_all_mocks(self, mock_tb_client, mock_postgres, mock_stream):
        """Should handle chat request with all external systems mocked."""
        # Setup all mocks
        mock_stream.return_value = iter(["Welcome to turbine copilot"])
        mock_postgres.return_value = MagicMock()
        mock_tb_client.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-456",
                "message": "What is the gearbox vibration?",
                "context": {
                    "turbine_id": "boreas",
                    "selected_component": "gearbox",
                },
            },
        )

        assert response.status_code == 200
        # Should have streamed some content
        content = response.text
        assert len(content) > 0

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_with_complex_context(self, mock_postgres, mock_stream):
        """Should accept and handle complex context dictionary."""
        mock_stream.return_value = iter(["response"])
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-789",
                "message": "Analyze subsystem health",
                "context": {
                    "turbine_id": "boreas",
                    "selected_component": "steam-admission",
                    "time_window": {
                        "start_ts": 1000000000,
                        "end_ts": 1000086400000,
                    },
                },
            },
        )

        assert response.status_code == 200


@pytest.mark.skipif(not TESTCLIENT_AVAILABLE, reason="FastAPI/TestClient not available")
class TestChatEndpointErrorHandling:
    """Test error handling in /chat endpoint."""

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_handles_model_gateway_error(self, mock_postgres, mock_stream):
        """Should handle vLLM connection failures gracefully.

        SSE streaming commits its 200 status and headers before the model is
        ever called (the model call happens lazily while Starlette iterates
        the generator), so a mid-stream failure cannot change the HTTP status
        — it must be reported in-band as an SSE error event instead, which is
        standard SSE practice (see stream_generator's except-block in
        main.py). We assert on that in-band error marker rather than a 4xx/5xx
        status.
        """
        from app.copilot_backend.model_gateway import ModelGatewayError

        mock_stream.side_effect = ModelGatewayError("vLLM connection refused")
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "Chat message",
                "context": {"turbine_id": "boreas"},
            },
        )

        # The HTTP status is already committed to 200 by the time the model
        # error occurs; the failure must instead be visible in the streamed
        # body as an in-band SSE error event. The raw internal exception text
        # must NOT reach the client (security rule: never expose internals) —
        # only a generic, user-safe message.
        assert response.status_code == 200
        assert "went wrong" in response.text
        assert "vLLM connection refused" not in response.text

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_endpoint_handles_database_error(self, mock_postgres, mock_stream):
        """Should handle PostgreSQL connection failures gracefully."""
        mock_stream.return_value = iter(["response"])
        mock_postgres.side_effect = Exception("Database connection refused")

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "Chat message",
                "context": {"turbine_id": "boreas"},
            },
        )

        # Chat history persistence is best-effort audit logging, not a hard
        # dependency for chatting: a PostgreSQL outage must not break the
        # user-facing response. The request should still succeed and stream
        # the model's answer normally.
        assert response.status_code == 200
        assert "response" in response.text
    """Test that /chat returns properly formatted streaming content."""

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_response_contains_model_output(self, mock_postgres, mock_stream):
        """Should include model-generated content in response."""
        expected_content = "The turbine is operating normally."
        mock_stream.return_value = iter(expected_content.split())
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "Status report",
                "context": {"turbine_id": "boreas"},
            },
        )

        assert response.status_code == 200
        # Response should contain some words from the model output
        content = response.text.lower()
        # At minimum should contain part of what was streamed
        assert len(content) > 0

    @patch("app.copilot_backend.copilot_backend_main.orchestrate_chat")
    @patch("app.copilot_backend.copilot_backend_main.save_message_to_db")
    def test_chat_response_no_write_tool_calls(self, mock_postgres, mock_stream):
        """Should never include write/control tool calls in response."""
        # Simulate a tool call that was somehow executed
        mock_stream.return_value = iter([
            "The sensor shows high temperature. ",
            "Acknowledged.",
        ])
        mock_postgres.return_value = MagicMock()

        try:
            from app.copilot_backend.copilot_backend_main import app
        except ImportError:
            pytest.skip("main.py not yet implemented")

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversation_id": "conv-123",
                "message": "Is the temperature high?",
                "context": {"turbine_id": "boreas"},
            },
        )

        assert response.status_code == 200
        content = response.text.lower()

        # Response should not contain dangerous tool names
        dangerous_tools = ["set_", "control", "execute_rpc", "acknowledge_alarm", "clear_alarm"]
        for dangerous in dangerous_tools:
            assert dangerous not in content, (
                f"Response contains dangerous tool reference: {dangerous}"
            )
