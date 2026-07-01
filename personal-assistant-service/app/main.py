import json
import logging
import time
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path

from app.logging_config import RequestLoggingMiddleware

logger = logging.getLogger("app")

from chainlit.utils import mount_chainlit  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field, StrictBool, ValidationError  # noqa: E402

from app.agent_handler import AgentHandler, get_agent_handler  # noqa: E402
from app.auth import (  # noqa: E402
    extract_gateway_session_id,
    extract_gateway_user_id,
    extract_workload_access_token,
)
from app.conversations import (  # noqa: E402
    assert_conversation_owner,
    migrate_legacy_conversation,
)
from app.settings import get_settings  # noqa: E402


class InvocationRequest(BaseModel):
    """Agent invocation request."""

    message: str = Field(description="User message sent to the Agent.")
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Durable Conversation ID. Web Chat always supplies this field; "
            "legacy non-Web channels may omit it during migration."
        ),
    )
    client_message_id: str | None = Field(
        default=None,
        description="Client-generated idempotency key for the user message.",
    )
    stream: StrictBool = Field(
        default=False,
        description="Return a Server-Sent Events stream instead of JSON.",
    )


class InvocationResponse(BaseModel):
    """Successful non-streaming invocation response."""

    response: str


class ErrorResponse(BaseModel):
    """HTTP error response."""

    detail: str


class LegacyMigrationRequest(BaseModel):
    """One-time migration hint from the authenticated legacy Web Chat."""

    legacy_session_id: str = Field(min_length=1, max_length=64)


def _parse_invocation_request(body: object) -> InvocationRequest:
    """Validate an invocation body while preserving the public 400 contract."""
    try:
        invocation = InvocationRequest.model_validate(body)
    except ValidationError as e:
        errors = e.errors()
        if any(
            error["loc"] == ("message",) and error["type"] == "missing"
            for error in errors
        ):
            detail = "message is required"
        elif any(error["loc"] == ("message",) for error in errors):
            detail = "message must be a string"
        elif any(error["loc"] == ("stream",) for error in errors):
            detail = "stream must be a boolean"
        else:
            detail = "invalid request body"
        raise HTTPException(status_code=400, detail=detail) from e

    if not invocation.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    return invocation


def _accepts_media_type(accept: str | None, media_type: str) -> bool:
    """Return whether an Accept header permits the selected response type."""
    if not accept:
        return True

    expected_type, expected_subtype = media_type.lower().split("/", maxsplit=1)
    for entry in accept.split(","):
        parts = [part.strip() for part in entry.split(";")]
        accepted_type = parts[0].lower()
        if "/" not in accepted_type:
            continue

        quality = 1.0
        for parameter in parts[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            continue

        accepted_main, accepted_subtype = accepted_type.split("/", maxsplit=1)
        if accepted_main in {"*", expected_type} and accepted_subtype in {
            "*",
            expected_subtype,
        }:
            return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # Validate LLM provider metadata. The Agent Bundle is built lazily after
    # the first request places the Gateway workload token in Runtime Context.
    from app.llm_config import validate_model_config

    try:
        validate_model_config()
    except ValueError as e:
        raise RuntimeError(f"LLM 配置错误: {e}") from e

    # Initialize the shared handler and persistent Checkpointer before serving.
    handler = get_agent_handler()
    await handler.startup()
    app.state.agent_handler = handler

    try:
        yield
    finally:
        await handler.shutdown()


app = FastAPI(
    title="Personal Assistant",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/ping")
async def ping():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post(
    "/invocations",
    response_model=InvocationResponse,
    responses={
        200: {
            "description": (
                "JSON response when stream is false, or a Server-Sent Events "
                "stream when stream is true."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": "Server-Sent Events stream.",
                    },
                    "example": (
                        'data: {"token":"你","done":false}\n\n'
                        'data: {"token":"","done":true}\n\n'
                    ),
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid JSON or invocation request.",
        },
        406: {
            "model": ErrorResponse,
            "description": "The Accept header excludes the selected response type.",
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": InvocationRequest.model_json_schema(),
                }
            },
        }
    },
)
async def invocations(request: Request):
    """Agent invocation endpoint, supporting sync JSON and SSE streaming."""
    try:
        body = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="invalid JSON body") from e

    invocation = _parse_invocation_request(body)
    message = invocation.message
    stream = invocation.stream
    user_id = extract_gateway_user_id(request)
    session_id = extract_gateway_session_id(request)
    conversation_id = invocation.conversation_id or session_id
    extract_workload_access_token(request)
    if invocation.conversation_id:
        await assert_conversation_owner(
            get_settings(),
            user_id,
            invocation.conversation_id,
        )

    mode = "stream" if stream else "sync"
    response_media_type = "text/event-stream" if stream else "application/json"
    if not _accepts_media_type(request.headers.get("accept"), response_media_type):
        raise HTTPException(
            status_code=406,
            detail=f"Accept header must allow {response_media_type}",
        )

    handler: AgentHandler = request.app.state.agent_handler
    started_at = time.perf_counter()
    logger.info("Invocation started mode=%s", mode)

    if stream:

        async def event_generator():
            status = "cancelled"
            try:
                async for sse_data in handler.handle_stream(
                    message=message,
                    user_id=user_id,
                    session_id=conversation_id,
                ):
                    yield sse_data
                status = "success"
            except Exception as e:
                status = "error"
                logger.error(
                    "Invocation failed mode=stream duration_ms=%.2f: %s",
                    (time.perf_counter() - started_at) * 1000,
                    e,
                    exc_info=True,
                )
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            finally:
                logger.info(
                    "Invocation completed mode=stream status=%s duration_ms=%.2f",
                    status,
                    (time.perf_counter() - started_at) * 1000,
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        result = await handler.handle(
            message=message,
            user_id=user_id,
            session_id=conversation_id,
        )
    except Exception as e:
        logger.error(
            "Invocation failed mode=sync duration_ms=%.2f: %s",
            (time.perf_counter() - started_at) * 1000,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

    logger.info(
        "Invocation completed mode=sync status=success duration_ms=%.2f",
        (time.perf_counter() - started_at) * 1000,
    )
    return JSONResponse(content=InvocationResponse(response=result).model_dump())


@app.post("/invocations/internal/legacy-conversation-migrations")
async def legacy_conversation_migration(
    body: LegacyMigrationRequest,
    request: Request,
):
    """Backfill one legacy Checkpoint without exposing arbitrary thread IDs."""
    user_id = extract_gateway_user_id(request)
    extract_workload_access_token(request)
    handler: AgentHandler = request.app.state.agent_handler
    state = await handler.get_thread_state(user_id, body.legacy_session_id)
    return await migrate_legacy_conversation(
        get_settings(),
        user_id,
        body.legacy_session_id,
        state,
    )


# === Chainlit Playground（Agent 调试 UI）===


@app.get("/playground", include_in_schema=False)
async def legacy_playground_redirect():
    """Redirect legacy /playground to /playground/ for browser compatibility."""
    return RedirectResponse(url="/playground/")


@app.get("/playground/", include_in_schema=False)
async def legacy_playground_slash_redirect():
    """Serve a legacy Chainlit-compatible shell that points at the new mount."""
    return HTMLResponse(
        """
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="0; url=/invocations/playground/">
            <title>Chainlit Playground</title>
          </head>
          <body>
            <main id="chainlit">Chainlit Playground</main>
            <a href="/invocations/playground/">Open Chainlit Playground</a>
          </body>
        </html>
        """
    )


@app.get("/invocations/playground", include_in_schema=False)
async def playground_redirect():
    """Redirect /playground to /playground/ (Chainlit mount requires trailing slash)."""
    return RedirectResponse(url="/invocations/playground/")


mount_chainlit(
    app=app,
    target=str(Path(__file__).parent / "playground.py"),
    path="/invocations/playground",
)
