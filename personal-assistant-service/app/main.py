import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("uvicorn")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.agent_handler import AgentHandler  # noqa: E402


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
    app.state.agent_handler = AgentHandler()

    yield


app = FastAPI(
    title="Personal Assistant",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/api/ping")
async def ping():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/invocations")
async def invocations(request: Request):
    """Synchronous agent invocation endpoint."""
    body = await request.json()
    message = body.get("message", "")
    user_id = request.headers.get("X-AgentArts-User-Id", "anonymous")
    session_id = request.headers.get("X-AgentArts-Session-Id")

    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    handler: AgentHandler = request.app.state.agent_handler
    result = await handler.handle(
        message=message,
        user_id=user_id,
        session_id=session_id,
    )

    return {"response": result}


@app.get("/api/chat/stream")
async def chat_stream(request: Request, q: str = ""):
    """Streaming chat endpoint using Server-Sent Events."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="query parameter 'q' is required")

    handler: AgentHandler = request.app.state.agent_handler

    async def event_generator():
        async for sse_data in handler.handle_stream(message=q, user_id="anonymous"):
            yield sse_data

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Static file serving for the web chat UI — MUST be mounted after all API routes
# Try monorepo relative path first (local dev), fall back to Docker container path
_proj_root = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = _proj_root / "personal-assistant-client" / "dist"
if not STATIC_DIR.is_dir():
    STATIC_DIR = Path("dist")  # Docker: /app/dist/

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="web")
else:
    logger.warning(
        f"前端构建产物目录不存在（已尝试: {_proj_root / 'personal-assistant-client' / 'dist'}, dist/）。"
        "开发模式下请使用 `npm run dev` 在 personal-assistant-client/ 独立启动前端。"
        "部署模式下请确保 `npm run build` 已在 personal-assistant-client/ 执行。"
    )
