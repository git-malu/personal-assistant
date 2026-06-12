"""Integration tests for app.main FastAPI application."""

import json
import os
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

    async def handle_stream(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ):
        self.stream_calls.append((message, user_id, session_id))
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
            "X-HW-AgentGateway-User-Id": "user-1",
            "x-hw-agentarts-session-id": "sess-abc",
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


# ---------------------------------------------------------------------------
# Header handling tests
# ---------------------------------------------------------------------------


class TestHeaderHandling:
    """Verify the /invocations endpoint reads AgentArts Gateway headers.

    - session_id: from x-hw-agentarts-session-id header (400 if missing)
    - user_id: from X-HW-AgentGateway-User-Id header (fail-closed: 401 if missing)
    """

    # ── session_id ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_session_id_from_official_header(self, client, fake_handler):
        """Official header x-hw-agentarts-session-id is recognized."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                "X-HW-AgentGateway-User-Id": "test-user",
                "x-hw-agentarts-session-id": "sess-123",
            },
        )
        assert fake_handler.handle_calls[0][2] == "sess-123"

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_400(self, client):
        """POST /invocations without x-hw-agentarts-session-id header returns 400."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={"X-HW-AgentGateway-User-Id": "test-user"},
        )
        assert response.status_code == 400
        assert "x-hw-agentarts-session-id" in response.json()["detail"]

    # ── user_id ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_user_id_from_official_gateway_header(self, client, fake_handler):
        """Official header X-HW-AgentGateway-User-Id is recognized."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                "X-HW-AgentGateway-User-Id": "user-x",
                "x-hw-agentarts-session-id": "sess-test",
            },
        )
        assert fake_handler.handle_calls[0][1] == "user-x"

    @pytest.mark.asyncio
    async def test_invocations_gateway_user_id_passed_to_handler(
        self, client, fake_handler
    ):
        """POST with X-HW-AgentGateway-User-Id: special-user →
        handler receives user_id='special-user'."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                "X-HW-AgentGateway-User-Id": "special-user",
                "x-hw-agentarts-session-id": "sess-test",
            },
        )
        assert fake_handler.handle_calls[0][1] == "special-user"

    @pytest.mark.asyncio
    async def test_user_id_anonymous_default(self, client):
        """No user-id header → fail-closed with 401."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={"x-hw-agentarts-session-id": "sess-default"},
        )
        assert response.status_code == 401
        assert "Missing X-HW-AgentGateway-User-Id header" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invocations_missing_gateway_user_id_returns_401(self, client):
        """POST /invocations with valid session_id but no user-id header → 401."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={"x-hw-agentarts-session-id": "sess-test"},
        )
        assert response.status_code == 401
        assert "Missing X-HW-AgentGateway-User-Id header" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invocations_stream_false_returns_response(client, fake_handler):
    """POST /invocations with stream=false keeps synchronous behavior."""
    response = await client.post(
        "/invocations",
        json={"message": "Hello, assistant!", "stream": False},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"response": "Hello, I am your assistant!"}
    assert len(fake_handler.handle_calls) == 1
    assert fake_handler.stream_calls == []


@pytest.mark.asyncio
async def test_invocations_empty_message_returns_400(client):
    """POST /invocations with empty message returns 400."""
    response = await client.post(
        "/invocations",
        json={"message": ""},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_missing_message_returns_400(client):
    """POST /invocations without 'message' field returns 400."""
    response = await client.post(
        "/invocations",
        json={},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"


@pytest.mark.asyncio
async def test_invocations_invalid_json_returns_400(client):
    """POST /invocations with invalid JSON returns 400."""
    response = await client.post(
        "/invocations",
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid JSON body"


@pytest.mark.asyncio
async def test_invocations_whitespace_only_passes_through(client, fake_handler):
    """Whitespace-only message is NOT rejected — app uses `if not message`
    which treats whitespace as truthy for synchronous invocations.
    """
    response = await client.post(
        "/invocations",
        json={"message": "   "},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
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
# POST /invocations with stream=true
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invocations_stream_returns_sse(client, fake_handler):
    """POST /invocations with stream=true returns text/event-stream."""
    response = await client.post(
        "/invocations",
        json={"message": "hello", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "user-1",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert "text/event-stream" in content_type, f"Got: {content_type}"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert fake_handler.stream_calls == [("hello", "user-1", "sess-test")]

    body = response.text
    assert "data:" in body
    assert '"token"' in body


@pytest.mark.asyncio
async def test_invocations_stream_content_format(client):
    """Verify SSE stream contains properly formatted JSON events."""
    response = await client.post(
        "/invocations",
        json={"message": "hello", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
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
async def test_invocations_stream_empty_message_returns_400(client):
    """POST /invocations with stream=true and empty message returns 400."""
    response = await client.post(
        "/invocations",
        json={"message": "", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 400
    assert "required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invocations_stream_missing_message_returns_400(client):
    """POST /invocations with stream=true and missing message returns 400."""
    response = await client.post(
        "/invocations",
        json={"stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 400
    assert "required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invocations_stream_whitespace_message_returns_400(client):
    """POST /invocations with stream=true and whitespace message returns 400."""
    response = await client.post(
        "/invocations",
        json={"message": "  ", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "sess-test",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_old_invocations_stream_route_returns_404(client):
    """GET /invocations/stream is removed for AgentArts ACCURATE_MATCH."""
    response = await client.get("/invocations/stream?q=hello")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Chainlit Playground mount (Feature 1.4)
# ---------------------------------------------------------------------------


class TestChainlitPlaygroundMount:
    """Tests for the Chainlit /invocations/playground mount (Feature 1.4)."""

    def test_playground_mount_exists(self):
        """FastAPI app includes a Mount at path /invocations/playground for Chainlit."""
        from app.main import app

        mounts = [r for r in app.routes if isinstance(r, Mount)]
        playground_routes = [m for m in mounts if m.path == "/invocations/playground"]
        assert len(playground_routes) == 1, (
            "Expected 1 Mount at /invocations/playground, "
            f"got {len(playground_routes)}. "
            f"All mounts: {[(m.path, m.name) for m in mounts]}"
        )

    def test_playground_mount_is_chainlit_app(self):
        """The /invocations/playground Mount wraps a Chainlit FastAPI app."""
        from fastapi import FastAPI

        from app.main import app

        mounts = [r for r in app.routes if isinstance(r, Mount)]
        playground_routes = [m for m in mounts if m.path == "/invocations/playground"]
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
        """GET /invocations/playground redirects to /invocations/playground/."""
        import httpx

        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as ac:
            response = await ac.get("/invocations/playground")
            assert response.status_code == 307, (
                f"Expected 307 Temporary Redirect, got {response.status_code}"
            )
            location = response.headers.get("location")
            assert location == "/invocations/playground/", (
                f"Expected location=/invocations/playground/, got location={location!r}"
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
        import app.agent_handler as agent_handler_module
        from app.main import app as fastapi_app

        # The module-level app may have agent_handler set from module import
        # Skip if not set (e.g. when lifespan hasn't run)
        if not hasattr(fastapi_app.state, "agent_handler"):
            pytest.skip("app.state.agent_handler not set (lifespan not triggered)")

        stored = fastapi_app.state.agent_handler
        if not isinstance(stored, agent_handler_module.AgentHandler):
            pytest.skip("app.state.agent_handler was injected by a test fixture")

        from_singleton = agent_handler_module.get_agent_handler()
        assert stored is from_singleton, (
            "app.state.agent_handler must be the singleton instance"
        )


# ---------------------------------------------------------------------------
# CORS Middleware (chore/agentarts-deploy)
# ---------------------------------------------------------------------------

ALLOWED_ORIGIN = (
    "https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"
)


class TestCORSMiddlewareRegistration:
    """Verify CORSMiddleware is properly registered in the FastAPI app."""

    def test_cors_middleware_in_middleware_stack(self):
        """CORSMiddleware should be present in app.user_middleware."""
        from fastapi.middleware.cors import CORSMiddleware

        from app.main import app

        middleware_classes = [mw.cls for mw in app.user_middleware]
        assert CORSMiddleware in middleware_classes, (
            f"Expected CORSMiddleware in middleware stack, "
            f"got: {[c.__name__ for c in middleware_classes]}"
        )

    def test_cors_middleware_allow_origins(self):
        """CORSMiddleware should allow the OBS static website origin (at minimum)."""
        from fastapi.middleware.cors import CORSMiddleware

        from app.main import app

        cors_mws = [mw for mw in app.user_middleware if mw.cls is CORSMiddleware]
        assert len(cors_mws) == 1, (
            f"Expected exactly one CORSMiddleware, got {len(cors_mws)}"
        )
        origins = cors_mws[0].kwargs["allow_origins"]
        assert ALLOWED_ORIGIN in origins, (
            f"Expected {ALLOWED_ORIGIN!r} to be in allow_origins, got {origins!r}"
        )

    def test_cors_middleware_allow_credentials(self):
        """CORSMiddleware should be configured with allow_credentials=True."""
        from fastapi.middleware.cors import CORSMiddleware

        from app.main import app

        cors_mws = [mw for mw in app.user_middleware if mw.cls is CORSMiddleware]
        assert cors_mws[0].kwargs["allow_credentials"] is True

    def test_cors_middleware_allow_methods_wildcard(self):
        """CORSMiddleware should allow all HTTP methods."""
        from fastapi.middleware.cors import CORSMiddleware

        from app.main import app

        cors_mws = [mw for mw in app.user_middleware if mw.cls is CORSMiddleware]
        assert cors_mws[0].kwargs["allow_methods"] == ["*"]

    def test_cors_middleware_allow_headers_wildcard(self):
        """CORSMiddleware should allow all request headers."""
        from fastapi.middleware.cors import CORSMiddleware

        from app.main import app

        cors_mws = [mw for mw in app.user_middleware if mw.cls is CORSMiddleware]
        assert cors_mws[0].kwargs["allow_headers"] == ["*"]


class TestCORSPreflight:
    """Test CORS preflight (OPTIONS) behavior via ASGI transport."""

    @pytest.mark.asyncio
    async def test_preflight_options_ping_with_correct_origin(self, client):
        """OPTIONS /ping with the allowed Origin returns 200 + CORS headers."""
        response = await client.options(
            "/ping",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200

        assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert "GET" in response.headers.get("access-control-allow-methods", "")

    @pytest.mark.asyncio
    async def test_preflight_options_ping_with_disallowed_origin(self, client):
        """OPTIONS /ping with a disallowed Origin should NOT include CORS
        allow-origin header."""
        response = await client.options(
            "/ping",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # The response will be 200 (endpoint itself works), but CORS headers
        # should NOT set the Origin as allowed.
        acao = response.headers.get("access-control-allow-origin")
        assert acao != "https://evil.example.com", (
            f"Disallowed origin should not be echoed: got {acao!r}"
        )

    @pytest.mark.asyncio
    async def test_preflight_options_invocations_with_correct_origin(self, client):
        """OPTIONS /invocations with the allowed Origin returns 200 +
        CORS headers."""
        response = await client.options(
            "/invocations",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "content-type,X-HW-AgentGateway-User-Id"
                ),
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
        assert response.headers.get("access-control-allow-credentials") == "true"


class TestCORSHeadersOnNormalRequests:
    """Verify CORS headers appear on normal (non-preflight) requests."""

    @pytest.mark.asyncio
    async def test_get_ping_includes_cors_headers(self, client):
        """GET /ping with allowed Origin returns Access-Control-Allow-Origin."""
        response = await client.get(
            "/ping",
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
        assert response.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_post_invocations_includes_cors_headers(self, client):
        """POST /invocations with allowed Origin returns CORS headers."""
        response = await client.post(
            "/invocations",
            json={"message": "Hello, assistant!"},
            headers={
                "Origin": ALLOWED_ORIGIN,
                "X-HW-AgentGateway-User-Id": "user-1",
                "x-hw-agentarts-session-id": "sess-test",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
        assert response.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_get_ping_without_origin_header_omits_cors(self, client):
        """GET /ping without any Origin header should NOT set allow-origin."""
        response = await client.get("/ping")
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers, (
            "Should NOT set CORS headers when no Origin is sent"
        )


class TestCORSEnvVar:
    """Test CORS_ALLOWED_ORIGINS environment variable behavior (feature-12)."""

    def test_cors_allowed_origins_from_env_var(self, monkeypatch):
        """When CORS_ALLOWED_ORIGINS is set, use it as comma-separated list."""
        import importlib

        from app import main as app_main

        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "https://a.example.com,https://b.example.com",
        )
        importlib.reload(app_main)

        try:
            from fastapi.middleware.cors import CORSMiddleware

            cors_mws = [
                mw for mw in app_main.app.user_middleware if mw.cls is CORSMiddleware
            ]
            origins = cors_mws[0].kwargs["allow_origins"]
            assert origins == ["https://a.example.com", "https://b.example.com"]
        finally:
            # Cleanup: reload without the env var to restore default state
            monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
            importlib.reload(app_main)

    def test_cors_empty_env_var_behavior(self, monkeypatch):
        """When CORS_ALLOWED_ORIGINS is set to empty string, falls back to defaults.

        An empty string is falsy in Python, so the condition
        ``if _env_origins`` evaluates to False and _default_origins is used.
        This is safe — an empty env var means "not configured", same as absent.
        """
        import importlib

        from app import main as app_main

        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
        importlib.reload(app_main)

        try:
            from fastapi.middleware.cors import CORSMiddleware

            cors_mws = [
                mw for mw in app_main.app.user_middleware if mw.cls is CORSMiddleware
            ]
            origins = cors_mws[0].kwargs["allow_origins"]
            # Empty string → falsy → falls back to default origins (same as unset)
            assert ALLOWED_ORIGIN in origins, (
                f"Empty CORS_ALLOWED_ORIGINS should fall back to defaults "
                f"(containing {ALLOWED_ORIGIN!r}), got {origins!r}"
            )
            # Verify it does NOT accidentally allow all origins
            assert "*" not in origins, (
                f"Empty CORS_ALLOWED_ORIGINS must not produce wildcard, got {origins!r}"
            )
        finally:
            monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
            importlib.reload(app_main)
