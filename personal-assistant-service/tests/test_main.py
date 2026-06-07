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
# GET /  (Static files)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_index_returns_html(client):
    """GET / returns the index.html content."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Personal Assistant" in response.text
    assert "<!doctype html>" in response.text


# ---------------------------------------------------------------------------
# StaticFiles dual-path discovery
# ---------------------------------------------------------------------------


class TestStaticFileDualPathDiscovery:
    """Tests for the dual-path static file discovery logic (Feature 1.1)."""

    def test_static_dir_points_to_monorepo_path(self):
        """STATIC_DIR uses monorepo path when personal-assistant-client/dist/ exists."""
        from app.main import STATIC_DIR, _proj_root

        expected = _proj_root / "personal-assistant-client" / "dist"
        assert str(STATIC_DIR) == str(expected), (
            f"Expected STATIC_DIR={expected}, got {STATIC_DIR}"
        )

    def test_static_files_route_is_mounted(self):
        """The StaticFiles route 'web' should be mounted at root when dist exists."""
        from app.main import app

        web_routes = [r for r in app.routes if getattr(r, "name", "") == "web"]
        assert len(web_routes) == 1, f"Expected 1 'web' route, got {len(web_routes)}"
        # Starlette represents root-mounted StaticFiles path as empty string
        assert web_routes[0].path == "", (
            f"Expected root path '', got {web_routes[0].path!r}"
        )

    def test_api_routes_take_precedence(self):
        """API routes must be registered before the catch-all StaticFiles mount."""
        from app.main import app

        # Routes are ordered by registration; name attribute identifies each route
        route_names = [getattr(r, "name", "") for r in app.routes]
        web_idx = route_names.index("web")
        ping_idx = route_names.index("ping")

        # API routes must precede static mount (lower index = registered first)
        assert ping_idx < web_idx, (
            f"/api/ping should be registered before static mount, "
            f"but ping={ping_idx}, web={web_idx}"
        )

    def test_invocations_route_precedes_static(self):
        """POST /api/invocations should precede the catch-all static mount."""
        from app.main import app

        route_names = [getattr(r, "name", "") for r in app.routes]
        web_idx = route_names.index("web")
        invocations_idx = route_names.index("invocations")

        assert invocations_idx < web_idx, (
            f"/api/invocations should be registered before static mount, "
            f"but invocations={invocations_idx}, web={web_idx}"
        )

    def test_graceful_degradation_when_no_dist(self, monkeypatch):
        """App should start without crashing when no static directory exists.

        When both monorepo path and Docker path are missing, the app must
        still be importable (no crash) and the StaticFiles mount should NOT
        be registered.
        """
        import importlib
        from pathlib import Path

        import app.main

        # Mock Path.is_dir to return False for all paths
        original_is_dir = Path.is_dir

        def mock_is_dir(self):
            return False

        monkeypatch.setattr(Path, "is_dir", mock_is_dir)

        # Reload app.main so STATIC_DIR is recomputed with our mock
        try:
            importlib.reload(app.main)
        except Exception as e:
            monkeypatch.undo()
            # Restore is_dir
            monkeypatch.setattr(Path, "is_dir", original_is_dir)
            importlib.reload(app.main)
            raise AssertionError(
                f"App should not crash when no static directory exists. Got: {e}"
            ) from e

        # After reload: verify no StaticFiles mount for "web"
        web_routes = [
            r for r in app.main.app.routes if getattr(r, "name", "") == "web"
        ]
        assert len(web_routes) == 0, (
            "StaticFiles 'web' route should NOT be mounted when no dist exists"
        )

        # Cleanup: restore original behavior for subsequent tests
        monkeypatch.setattr(Path, "is_dir", original_is_dir)
        importlib.reload(app.main)

    def test_warning_logged_when_no_dist_found(self, monkeypatch, caplog):
        """A warning must be emitted when no static directory is found."""
        import importlib
        import logging
        from pathlib import Path

        import app.main

        # Store original
        original_is_dir = Path.is_dir

        def mock_is_dir(self):
            return False

        monkeypatch.setattr(Path, "is_dir", mock_is_dir)

        # Capture logs at WARNING level
        caplog.set_level(logging.WARNING)

        try:
            importlib.reload(app.main)
        finally:
            # Restore
            monkeypatch.setattr(Path, "is_dir", original_is_dir)
            importlib.reload(app.main)

        # Check warning was logged
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1, (
            f"Expected at least 1 warning log, got {len(warnings)}"
        )
        # Verify the log contains the expected Chinese message
        warning_text = warnings[0].message
        assert "前端构建产物目录不存在" in warning_text, (
            "Expected warning about missing frontend build dir, "
            f"got: {warning_text!r}"
        )
        assert "personal-assistant-client" in warning_text, (
            f"Warning should mention monorepo path, got: {warning_text!r}"
        )
        assert "npm run dev" in warning_text, (
            f"Warning should mention dev mode instructions, got: {warning_text!r}"
        )
        assert "npm run build" in warning_text, (
            f"Warning should mention build instructions, got: {warning_text!r}"
        )

    def test_no_warning_when_dist_exists(self, caplog):
        """No warning should be logged when static directory is found."""
        import importlib
        import logging

        import app.main

        caplog.set_level(logging.WARNING)

        # Reload under normal conditions (dist exists)
        importlib.reload(app.main)

        # No warnings should be emitted for static file discovery
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        static_warnings = [
            w for w in warnings if "前端构建产物目录不存在" in w.message
        ]
        assert len(static_warnings) == 0, (
            f"No static-file warning expected when dist exists, got: {warnings}"
        )
