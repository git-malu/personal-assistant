import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent_handler import AgentHandler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # Check required environment variables
    if not os.environ.get("MODEL_API_KEY"):
        raise RuntimeError("MODEL_API_KEY environment variable is required but not set")

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
app.mount("/", StaticFiles(directory="web", html=True), name="web")
