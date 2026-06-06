"""Integration tests for app.main FastAPI application."""

import json
import os
from unittest.mock import patch

import httpx
import pytest

# Must be set BEFORE importing app.main (the lifespan checks this)
os.environ["MODEL_API_KEY"] = "test-key"

from app.main import app  # noqa: E402


class FakeAgentHandler:
    """A fake AgentHandler with predictable responses for integration tests."""

    def __init__(self, *, handle_response="Hello, I am your assistant!"):
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []
        self._handle_response = handle_response

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        return self._handle_response

    async def handle_stream(self, message: str, user_id: str = "anonymous"):
        self.stream_calls.append((message, user_id))
        yield 'data: {"token": "Hello", "done": false}\n\n'
        yield 'data: {"token": " world", "done": false}\n\n'
        yield 'data: {"token": "", "done": true}\n\n'


@pytest.fixture
def fake_handler():
    """Create a FakeAgentHandler and patch AgentHandler to use it."""
    handler = FakeAgentHandler()
    with patch("app.main.AgentHandler", return_value=handler):
        yield handler


@pytest.fixture
async def client(fake_handler):
    """Async HTTP client for testing the FastAPI app.

    Sets app.state.agent_handler directly because httpx.ASGITransport
    does not automatically trigger the FastAPI lifespan context.
    """
    app.state.agent_handler = fake_handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/ping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_status_ok(client):
    """GET /api/ping should return {"status": "ok"} with 200."""
    response = await client.get("/api/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/invocations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invocations_returns_response(client, fake_handler):
    """POST /api/invocations with valid payload returns 200 and response."""
    response = await client.post(
        "/api/invocations",
        json={"message": "Hello, assistant!"},
        headers={
            "X-AgentArts-User-Id": "user-1",
            "X-AgentArts-Session-Id": "sess-abc",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert data["response"] == "Hello, I am your assistant!"
    assert len(fake_handler.handle_calls) == 1
    assert fake_handler.handle_calls[0][0] == "Hello, assistant!"
    assert fake_handler.handle_calls[0][1] == "user-1"
    assert fake_handler.handle_calls[0][2] == "sess-abc"


@pytest.mark.asyncio
async def test_invocations_defaults_to_anonymous_user(client, fake_handler):
    """POST /api/invocations without X-AgentArts-User-Id defaults to 'anonymous'."""
    await client.post("/api/invocations", json={"message": "Hi"})
    assert fake_handler.handle_calls[0][1] == "anonymous"


@pytest.mark.asyncio
async def test_invocations_empty_message_returns_400(client):
    """POST /api/invocations with empty message returns 400."""
    response = await client.post("/api/invocations", json={"message": ""})
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_missing_message_returns_400(client):
    """POST /api/invocations without 'message' field returns 400."""
    response = await client.post("/api/invocations", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_whitespace_only_passes_through(client, fake_handler):
    """Whitespace-only message is NOT rejected — app uses `if not message`
    which treats whitespace as truthy. This is an inconsistency with
    /api/chat/stream which uses `q.strip()`. Should be fixed upstream.
    """
    response = await client.post("/api/invocations", json={"message": "   "})
    # Currently passes through; should be 400 after fix
    assert response.status_code == 200
    assert len(fake_handler.handle_calls) == 1


# ---------------------------------------------------------------------------
# App startup error (missing MODEL_API_KEY)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_model_api_key_causes_startup_error(monkeypatch):
    """App lifespan should raise RuntimeError when MODEL_API_KEY is missing."""
    # Temporarily remove MODEL_API_KEY from the environment
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    from fastapi import FastAPI

    from app.main import lifespan

    test_app = FastAPI()

    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        async with lifespan(test_app):
            pass


@pytest.mark.asyncio
async def test_lifespan_sets_agent_handler(fake_handler):
    """Test that lifespan initializes agent_handler on app state."""
    from fastapi import FastAPI

    from app.main import lifespan

    test_app = FastAPI()

    async with lifespan(test_app):
        assert test_app.state.agent_handler is fake_handler


# ---------------------------------------------------------------------------
# GET /api/chat/stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_returns_sse(client):
    """GET /api/chat/stream?q=hello returns 200 with text/event-stream."""
    response = await client.get("/api/chat/stream?q=hello")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert "text/event-stream" in content_type, f"Got: {content_type}"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"

    body = response.text
    assert "data:" in body
    assert '"token"' in body


@pytest.mark.asyncio
async def test_chat_stream_content_format(client):
    """Verify SSE stream contains properly formatted JSON events."""
    response = await client.get("/api/chat/stream?q=hello")
    assert response.status_code == 200

    body = response.text
    lines = [line for line in body.split("\n") if line]

    # Parse the SSE data lines
    events = []
    for line in lines:
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have both token events and a done event
    tokens = [e for e in events if not e.get("done")]
    done_events = [e for e in events if e.get("done")]

    assert len(tokens) >= 1
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_chat_stream_empty_query_returns_400(client):
    """GET /api/chat/stream?q= (empty) returns 400."""
    response = await client.get("/api/chat/stream?q=")
    assert response.status_code == 400
    assert "required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_stream_missing_query_returns_400(client):
    """GET /api/chat/stream without query param returns 400."""
    response = await client.get("/api/chat/stream")
    assert response.status_code == 400
    assert "required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chat_stream_whitespace_query_returns_400(client):
    """GET /api/chat/stream?q=%20%20 (spaces) returns 400."""
    response = await client.get("/api/chat/stream?q=%20%20")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /  (Static files)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_index_returns_html(client):
    """GET / returns the index.html content."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Personal Assistant" in response.text
    assert "<!DOCTYPE html>" in response.text
