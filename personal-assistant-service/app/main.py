import json
import logging
import os
import uuid
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # Validate LLM configuration per config.yaml, with fallback to legacy env vars.
    from app.llm_config import get_model

    try:
        get_model()  # validates provider config + api key availability
    except ValueError as e:
        raise RuntimeError(f"LLM 配置错误: {e}") from e

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
    user_id = request.headers.get("X-HW-AgentGateway-User-Id", "anonymous")
    session_id = request.headers.get("x-hw-agentarts-session-id")
    set_cookie = None

    # Cookie fallback: only when header is missing
    if not session_id:
        fallback_id = request.cookies.get("x-anonymous-session-id")
        if fallback_id:
            session_id = fallback_id
        else:
            session_id = str(uuid.uuid4())
            # Gate on ENV=development: only set cookie in dev
            if os.environ.get("ENV") == "development":
                set_cookie = (
                    f"x-anonymous-session-id={session_id}; "
                    f"Path=/; HttpOnly; SameSite=Lax"
                )

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    handler: AgentHandler = request.app.state.agent_handler

    if stream:
        if not message.strip():
            raise HTTPException(status_code=400, detail="message is required")

        async def event_generator():
            try:
                async for sse_data in handler.handle_stream(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                ):
                    yield sse_data
            except Exception as e:
                logger.error(f"Stream generator error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

        stream_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        if set_cookie:
            stream_headers["Set-Cookie"] = set_cookie

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=stream_headers,
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

    headers = {}
    if set_cookie:
        headers["Set-Cookie"] = set_cookie
    return JSONResponse(content={"response": result}, headers=headers)


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
