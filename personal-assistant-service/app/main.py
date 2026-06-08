import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("uvicorn")

from chainlit.utils import mount_chainlit  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import RedirectResponse, StreamingResponse  # noqa: E402

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


@app.get("/ping")
async def ping():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/invocations")
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


# === Chainlit Playground（Agent 调试 UI）===


@app.get("/playground", include_in_schema=False)
async def playground_redirect():
    """Redirect /playground to /playground/ (Chainlit mount requires trailing slash)."""
    return RedirectResponse(url="/playground/")


mount_chainlit(app=app, target=str(Path(__file__).parent / "playground.py"), path="/playground")

