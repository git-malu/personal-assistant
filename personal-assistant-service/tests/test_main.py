"""Integration tests for app.main FastAPI application."""

import asyncio
from unittest.mock import patch

import httpx
import pytest
from starlette.routing import Mount  # noqa: E402

from app.main import app  # noqa: E402
from app.settings import Settings


class FakeAgentHandler:
    """A fake AgentHandler with predictable responses for integration tests."""

    def __init__(self, *, handle_response="Hello, I am your assistant!"):
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []
        self._handle_response = handle_response
        self.startup_calls = 0
        self.shutdown_calls = 0

    async def startup(self):
        self.startup_calls += 1

    async def shutdown(self):
        self.shutdown_calls += 1

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
        message_queue: "asyncio.Queue | None" = None,  # NEW
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
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_id_is_preserved_when_safe(client):
    response = await client.get("/ping", headers={"X-Request-ID": "request-123"})

    assert response.headers["x-request-id"] == "request-123"


@pytest.mark.asyncio
async def test_unsafe_request_id_is_replaced(client):
    response = await client.get("/ping", headers={"X-Request-ID": "bad request id"})

    assert response.headers["x-request-id"] != "bad request id"
    assert len(response.headers["x-request-id"]) == 32


# Invocation behavior is covered by integration/test_invocations.py.
# ---------------------------------------------------------------------------
# App startup validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_llm_provider_causes_startup_error(monkeypatch):
    """App lifespan fails fast when the canonical Provider is unknown."""
    from fastapi import FastAPI

    from app.main import lifespan

    invalid_settings = Settings(_env_file=None, llm_provider="unknown")
    with patch(
        "app.llm_config.get_settings",
        return_value=invalid_settings,
    ):
        test_app = FastAPI()
        with pytest.raises(RuntimeError, match="Unknown LLM_PROVIDER"):
            async with lifespan(test_app):
                pass


@pytest.mark.asyncio
async def test_lifespan_sets_agent_handler(fake_handler):
    """Test that lifespan initializes agent_handler on app state."""
    from fastapi import FastAPI

    from app.main import lifespan

    test_app = FastAPI()
    with patch("app.llm_config.validate_model_config"):
        async with lifespan(test_app):
            assert test_app.state.agent_handler is fake_handler
            assert fake_handler.startup_calls == 1
        assert fake_handler.shutdown_calls == 1


# Streaming Invocation behavior is covered by integration/test_invocations.py.
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
            with patch("app.llm_config.validate_model_config"):

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


# CORS intentionally absent: Web Chat uses the same-origin proxy topology.
