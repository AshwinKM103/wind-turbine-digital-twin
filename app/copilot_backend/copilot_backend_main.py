"""FastAPI copilot backend for wind turbine digital twin chatbot."""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Local imports
try:
    from app.copilot_backend.orchestrator import orchestrate_chat
except ImportError:
    from orchestrator import orchestrate_chat

try:
    from app.copilot_backend.thingsboard_tools import resolve_turbine_device, ToolError
except ImportError:
    from thingsboard_tools import resolve_turbine_device, ToolError

from app.tools.thingsboard_client import ThingsboardClient, ThingsboardConfig

# Try to load structured logging; fall back to basicConfig if unavailable
try:
    try:
        from app.src.infrastructure import configure_logging
    except ImportError:
        from app.src.logging_config import configure_logging

    logger = configure_logging("copilot-backend")
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("copilot-backend")

# Global ThingsboardClient instance
_tb_client: Optional[ThingsboardClient] = None


def get_tb_client() -> ThingsboardClient:
    """Dependency to get the authenticated ThingsboardClient."""
    if _tb_client is None:
        raise RuntimeError("ThingsboardClient not initialized during startup")
    return _tb_client


# ===== Request/Response Schemas =====


class TimeWindow(BaseModel):
    """Optional time window for historical queries."""

    start_ts: int = Field(..., description="Start timestamp in milliseconds (Unix epoch)")
    end_ts: int = Field(..., description="End timestamp in milliseconds (Unix epoch)")


class ChatContext(BaseModel):
    """Optional contextual metadata about the dashboard state."""

    turbine_id: str = Field(..., description="Turbine identifier or ThingsBoard device ID")
    dashboard_state: Optional[str] = Field(
        None,
        description="Current dashboard view or context (e.g., 'overview', 'alerts', 'performance')",
    )
    selected_component: Optional[str] = Field(
        None, description="User-selected component for narrowed focus (e.g., 'gearbox', 'generator')"
    )
    time_window: Optional[TimeWindow] = Field(None, description="Historical time range for queries")


class ChatRequest(BaseModel):
    """Request payload for /chat endpoint."""

    conversation_id: Optional[str] = Field(
        None, description="Unique conversation ID; auto-generated if omitted"
    )
    message: str = Field(..., description="User message / question", min_length=1, max_length=2048)
    context: ChatContext = Field(..., description="Dashboard context for tool scoping")


# ===== Lifespan and Startup/Shutdown =====


async def startup_thingsboard() -> None:
    """Initialize and authenticate ThingsboardClient on app startup."""
    global _tb_client

    tb_host = os.environ.get("TB_HOST", "thingsboard")
    tb_port = int(os.environ.get("TB_PORT", "8080"))
    tb_admin_email = os.environ.get("TENANT_EMAIL") or os.environ.get("TB_TENANT_ADMIN_EMAIL") or os.environ.get("TB_ADMIN_EMAIL")
    tb_admin_password = os.environ.get("TB_TENANT_ADMIN_PASSWORD") or os.environ.get("TB_ADMIN_PASSWORD")

    if not tb_admin_email or not tb_admin_password:
        raise RuntimeError(
            "TENANT_EMAIL (or TB_ADMIN_EMAIL) and TB_TENANT_ADMIN_PASSWORD (or TB_ADMIN_PASSWORD) environment variables must be set. "
            "Copilot cannot function without ThingsBoard connectivity."
        )

    config = ThingsboardConfig(
        host=tb_host,
        port=tb_port,
        admin_email=tb_admin_email,
        admin_password=tb_admin_password,
    )

    _tb_client = ThingsboardClient(config)
    if not _tb_client.authenticate():
        raise RuntimeError("Failed to authenticate with ThingsBoard. Check credentials and connectivity.")

    logger.info("✓ ThingsboardClient initialized and authenticated")


async def shutdown_thingsboard() -> None:
    """Logout from ThingsBoard on app shutdown."""
    global _tb_client
    if _tb_client:
        _tb_client.logout()
        logger.info("✓ ThingsboardClient logged out")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context: startup and shutdown events."""
    await startup_thingsboard()
    yield
    await shutdown_thingsboard()


# ===== FastAPI App Setup =====

app = FastAPI(
    title="Turbine Copilot Backend",
    description="READ-ONLY diagnostic chatbot for wind turbine digital twin",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: allow all origins for MVP (internal network only)
# TODO: restrict to specific frontend origin in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Authentication Dependency =====


def verify_api_key(authorization: Optional[str] = Header(None)) -> str:
    """Optional bearer token authentication.

    If COPILOT_API_KEY env var is set, require Authorization: Bearer <key>.
    If unset, skip auth (Phase 1 MVP: single shared operator identity).
    """
    api_key = os.environ.get("COPILOT_API_KEY")
    if not api_key:
        # No auth configured; allow all requests
        return "anonymous"

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    if parts[1] != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return "authenticated"


# ===== Health Check =====


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for load balancers and orchestrators."""
    return {"status": "ok"}


# ===== Chat Endpoint =====


async def stream_generator(
    request: ChatRequest,
    tb_client: ThingsboardClient,
) -> None:
    """Generate SSE events for streaming chat response."""
    conversation_id = request.conversation_id or str(uuid.uuid4())

    # Persist the user message best-effort: an audit-log write failure must
    # never take down the chat response itself (chatting still works even if
    # PostgreSQL is briefly unavailable).
    try:
        await save_message_to_db(
            conversation_id=conversation_id,
            role="user",
            content=request.message,
        )
    except Exception as e:
        logger.warning(f"Failed to persist user message to PostgreSQL: {e}")

    # Build conversation history from database (TODO: fetch prior turns)
    conversation_history = []

    # Resolve the dashboard-supplied turbine_id to a server-verified ThingsBoard
    # device *before* handing anything to the model. The model/widget must never
    # be trusted to name its own entity ID (see tb_tools.resolve_turbine_device).
    try:
        resolved_entity = resolve_turbine_device(tb_client, request.context.turbine_id)
    except ToolError as e:
        logger.warning(
            f"Turbine resolution failed for conversation {conversation_id}: {e}"
        )
        yield (
            "data: "
            + json.dumps(
                "I couldn't find that turbine in ThingsBoard. Please check the "
                "dashboard is pointed at a valid device and try again."
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"
        return

    # Orchestrate the chat loop and stream response. Chunks are normally
    # plain text strings; render_chart/open_dashboard tool calls also emit
    # structured dict chunks (e.g. {"type": "chart", "spec": {...}}) for the
    # widget to render directly. Only text chunks accumulate into the
    # transcript persisted to Postgres below.
    full_response = ""
    try:
        for chunk in orchestrate_chat(
            user_message=request.message,
            conversation_history=conversation_history,
            tb_client=tb_client,
            resolved_entity=resolved_entity,
        ):
            if isinstance(chunk, str):
                full_response += chunk
            # SSE format: data: <json-encoded-value>\n\n
            yield f"data: {json.dumps(chunk)}\n\n"

        # Save assistant response to PostgreSQL (also best-effort)
        try:
            await save_message_to_db(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
            )
        except Exception as e:
            logger.warning(f"Failed to persist assistant message to PostgreSQL: {e}")

        # Send completion marker
        yield "data: [DONE]\n\n"

    except Exception as e:
        # Log the full internal detail server-side, but never leak raw
        # exception text (internal hosts, stack detail) to the chat UI.
        logger.error(f"Error in chat stream: {e}")
        yield (
            "data: "
            + json.dumps("Something went wrong while generating a response. Please try again.")
            + "\n\n"
        )
        yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    _: str = Depends(verify_api_key),
    tb_client: ThingsboardClient = Depends(get_tb_client),
) -> StreamingResponse:
    """POST /chat endpoint: stream chat responses as Server-Sent Events.

    Request body:
    {
        "conversation_id": "optional-id",
        "message": "user question",
        "context": {
            "turbine_id": "device-id",
            "dashboard_state": "overview",
            "selected_component": null,
            "time_window": null
        }
    }

    Response: text/event-stream (SSE) of model output chunks.
    """
    conversation_id = request.conversation_id or str(uuid.uuid4())

    logger.info(
        f"Chat request",
        extra={
            "conversation_id": conversation_id,
            "message_length": len(request.message),
            "turbine_id": request.context.turbine_id,
        },
    )

    # Return streaming response
    return StreamingResponse(
        stream_generator(request, tb_client),
        media_type="text/event-stream",
    )


# ===== Database Helpers =====


async def save_message_to_db(conversation_id: str, role: str, content: str) -> None:
    """Save a chat message to PostgreSQL for audit and context retrieval.

    Args:
        conversation_id: unique conversation identifier
        role: 'user' or 'assistant'
        content: message text
    """
    try:
        import psycopg

        db_user = os.environ.get("POSTGRES_USER", "turbine")
        db_pass = os.environ.get("POSTGRES_PASSWORD")
        if not db_pass:
            logger.warning("POSTGRES_PASSWORD not set; skipping PostgreSQL message persistence")
            return
        db_name = os.environ.get("POSTGRES_DB", "turbine")

        # Try exposed port first, then container port
        conn = None
        for port in [15432, 5432]:
            try:
                conn = psycopg.connect(
                    f"postgresql://{db_user}:{db_pass}@127.0.0.1:{port}/{db_name}",
                    connect_timeout=3,
                )
                break
            except Exception:
                pass

        if not conn:
            logger.warning("Could not connect to PostgreSQL for message persistence")
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO copilot_conversations (conversation_id, role, content)
                    VALUES (%s, %s, %s)
                    """,
                    (conversation_id, role, content),
                )
                conn.commit()
        finally:
            conn.close()

    except Exception as e:
        logger.warning(f"Failed to save message to PostgreSQL: {e}")


# ===== Entry Point =====

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("COPILOT_PORT", 8000)),
        log_config=None,  # Use app's logging config
    )
