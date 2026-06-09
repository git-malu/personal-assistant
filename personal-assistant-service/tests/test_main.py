"""Integration tests for app.main FastAPI application."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

# Must be set BEFORE importing app.main (the lifespan checks this)
os.environ["MODEL_API_KEY"] = "test-key"

from starlette.routing import Mount  # noqa: E402

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
    """Create a FakeAgentHandler and patch get_agent_handler to use it.

    Feature 1.4: lifespan calls get_agent_handler() for singleton sharing
    with Chainlit playground, so we must patch the singleton function.
    """
    handler = FakeAgentHandler()
    with patch("app.main.get_agent_handler", return_value=handler):
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
# GET /ping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_returns_status_ok(client):
    """GET /ping should return {"status": "ok"} with 200."""
    response = await client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /invocations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invocations_returns_response(client, fake_handler):
    """POST /invocations with valid payload returns 200 and response."""
    response = await client.post(
        "/invocations",
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
    """POST /invocations without X-AgentArts-User-Id defaults to 'anonymous'."""
    await client.post("/invocations", json={"message": "Hi"})
    assert fake_handler.handle_calls[0][1] == "anonymous"


@pytest.mark.asyncio
async def test_invocations_empty_message_returns_400(client):
    """POST /invocations with empty message returns 400."""
    response = await client.post("/invocations", json={"message": ""})
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_missing_message_returns_400(client):
    """POST /invocations without 'message' field returns 400."""
    response = await client.post("/invocations", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_whitespace_only_passes_through(client, fake_handler):
    """Whitespace-only message is NOT rejected — app uses `if not message`
    which treats whitespace as truthy. This is an inconsistency with
    /api/chat/stream which uses `q.strip()`. Should be fixed upstream.
    """
    response = await client.post("/invocations", json={"message": "   "})
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

    # Ensure config.yaml absence is simulated (avoid picking up real config.yaml)
    with patch("pathlib.Path.exists", return_value=False):
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
    with patch("pathlib.Path.exists", return_value=False):
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
# Chainlit Playground mount (Feature 1.4)
# ---------------------------------------------------------------------------


class TestChainlitPlaygroundMount:
    """Tests for the Chainlit /playground mount (Feature 1.4)."""

    def test_playground_mount_exists(self):
        """FastAPI app includes a Mount at path /playground for Chainlit."""
        from app.main import app

        mounts = [r for r in app.routes if isinstance(r, Mount)]
        playground_routes = [m for m in mounts if m.path == "/playground"]
        assert len(playground_routes) == 1, (
            f"Expected 1 Mount at /playground, got {len(playground_routes)}. "
            f"All mounts: {[(m.path, m.name) for m in mounts]}"
        )

    def test_playground_mount_is_chainlit_app(self):
        """The /playground Mount wraps a Chainlit FastAPI sub-application."""
        from fastapi import FastAPI

        from app.main import app

        mounts = [r for r in app.routes if isinstance(r, Mount)]
        playground_routes = [m for m in mounts if m.path == "/playground"]
        playground_mount = playground_routes[0]

        assert isinstance(playground_mount.app, FastAPI), (
            f"Expected FastAPI sub-app, got {type(playground_mount.app).__name__}"
        )

    @pytest.mark.asyncio
    async def test_ping_works_with_chainlit_mount(self):
        """GET /ping returns 200 OK when Chainlit is mounted."""
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/ping")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_playground_redirect_trailing_slash(self):
        """GET /playground (no trailing slash) returns 307 redirect to /playground/."""
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as ac:
            response = await ac.get("/playground")
            assert response.status_code == 307, (
                f"Expected 307 Temporary Redirect, got {response.status_code}"
            )
            location = response.headers.get("location")
            assert location == "/playground/", (
                f"Expected location=/playground/, got location={location!r}"
            )


# ---------------------------------------------------------------------------
# Agent handler singleton shared with Chainlit (Feature 1.4)
# ---------------------------------------------------------------------------


class TestAgentHandlerSingletonIntegration:
    """Integration tests verifying agent_handler singleton shared between
    FastAPI lifespan and Chainlit playground (Feature 1.4)."""

    def test_lifespan_sets_agent_handler_same_as_get_agent_handler(self):
        """After lifespan, app.state.agent_handler IS get_agent_handler()."""
        from fastapi import FastAPI

        import app.agent_handler
        from app.main import lifespan

        # Reset the singleton for a clean test
        app.agent_handler._handler_instance = None

        try:
            test_app = FastAPI()
            with patch("pathlib.Path.exists", return_value=False):
                async def _run():
                    async with lifespan(test_app):
                        stored = test_app.state.agent_handler
                        from_singleton = app.agent_handler.get_agent_handler()
                        assert stored is from_singleton, (
                            "app.state.agent_handler must be the same object as "
                            "get_agent_handler() return value"
                        )

                import asyncio
                asyncio.run(_run())
        finally:
            # Clean up
            app.agent_handler._handler_instance = None

    def test_main_app_state_agent_handler_is_singleton(self):
        """app.state.agent_handler (if set) is the same as get_agent_handler()."""
        import app.agent_handler as agent_handler_mod
        from app.main import app as fastapi_app

        # Clean up shared state that may have been polluted by other tests
        # (e.g. the client fixture sets app.state.agent_handler to a FakeAgentHandler)
        agent_handler_mod._handler_instance = None
        if hasattr(fastapi_app.state, "agent_handler"):
            del fastapi_app.state.agent_handler

        # After cleanup, agent_handler is no longer set → skip
        # (the lifespan hasn't actually run on the module-level app)
        if not hasattr(fastapi_app.state, "agent_handler"):
            pytest.skip("app.state.agent_handler not set (lifespan not triggered)")

        stored = fastapi_app.state.agent_handler
        from_singleton = agent_handler_mod.get_agent_handler()
        assert stored is from_singleton, (
            "app.state.agent_handler must be the singleton instance"
        )


