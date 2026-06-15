import json
import logging
import os
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("uvicorn")

from chainlit.utils import mount_chainlit  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import (  # noqa: E402
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)

from app.agent_handler import AgentHandler, get_agent_handler  # noqa: E402
from app.identity import (  # noqa: E402
    capture_runtime_context,
    get_runtime_session_id,
    get_runtime_user_id,
    request_runtime_context,
    runtime_context_scope,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # Initialize agent handler
    app.state.agent_handler = get_agent_handler()

    yield


app = FastAPI(
    title="Personal Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

_default_origins = [
    "https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"
]
_env_origins = os.getenv("CORS_ALLOWED_ORIGINS")
_allowed_origins = (
    [o.strip() for o in _env_origins.split(",")] if _env_origins else _default_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def agentarts_runtime_context_middleware(request: Request, call_next):
    """Seed AgentArts SDK runtime context from Gateway headers for each request."""

    with request_runtime_context(request.headers):
        return await call_next(request)


@app.get("/ping")
async def ping():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post(
    "/invocations",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {"type": "string"},
                            "stream": {"type": "boolean", "default": False},
                        },
                    }
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

    message = body.get("message", "")
    stream = body.get("stream", False)
    user_id = get_runtime_user_id() or "anonymous"
    session_id = get_runtime_session_id()
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="x-hw-agentarts-session-id header is required",
        )

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    handler: AgentHandler = request.app.state.agent_handler

    if stream:
        if not message.strip():
            raise HTTPException(status_code=400, detail="message is required")

        runtime_context = capture_runtime_context()

        async def event_generator():
            try:
                with runtime_context_scope(runtime_context):
                    async for sse_data in handler.handle_stream(
                        message=message,
                        user_id=user_id,
                        session_id=session_id,
                    ):
                        yield sse_data
            except Exception as e:
                logger.error(f"Stream generator error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

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
            session_id=session_id,
        )
    except Exception as e:
        logger.error(f"Agent handler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return JSONResponse(content={"response": result})


# === Chainlit Playground（Agent 调试 UI）===


@app.get("/invocations/playground", include_in_schema=False)
async def playground_redirect():
    """Redirect /playground to /playground/ (Chainlit mount requires trailing slash)."""
    return RedirectResponse(url="/invocations/playground/")


mount_chainlit(
    app=app,
    target=str(Path(__file__).parent / "playground.py"),
    path="/invocations/playground",
)
