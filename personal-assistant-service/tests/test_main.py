"""Integration tests for app.main FastAPI application."""

import asyncio
import json
from unittest.mock import ANY, patch

import httpx
import pytest
from agentarts.sdk.runtime.context import AgentArtsRuntimeContext
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from starlette.routing import Mount  # noqa: E402

from app.main import app  # noqa: E402
from app.oauth2_state import verify_oauth2_state
from app.settings import get_settings


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


# ---------------------------------------------------------------------------
# POST /invocations
# ---------------------------------------------------------------------------


def test_invocations_openapi_documents_json_and_sse_responses():
    """The generated OpenAPI contract documents both response media types."""
    operation = app.openapi()["paths"]["/invocations"]["post"]
    response = operation["responses"]["200"]
    content = response["content"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert set(content) == {"application/json", "text/event-stream"}
    assert content["application/json"]["schema"] == {
        "$ref": "#/components/schemas/InvocationResponse"
    }
    assert content["text/event-stream"]["schema"]["type"] == "string"
    assert request_schema["required"] == ["message"]
    assert request_schema["properties"]["stream"]["type"] == "boolean"
    assert set(operation["responses"]) >= {"200", "400", "406"}


@pytest.mark.asyncio
async def test_invocations_returns_response(client, fake_handler):
    """POST /invocations with valid payload returns 200 and response."""
    response = await client.post(
        "/invocations",
        json={"message": "Hello, assistant!"},
        headers={
            USER_ID_HEADER: "user-1",
            SESSION_HEADER: "sess-abc",
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
async def test_invocations_sets_oauth2_custom_state_for_calendar(client):
    response = await client.post(
        "/invocations",
        json={"message": "Hello, assistant!"},
        headers={
            USER_ID_HEADER: "user-1",
            SESSION_HEADER: "sess-abc",
        },
    )

    assert response.status_code == 200
    claims = verify_oauth2_state(
        AgentArtsRuntimeContext.get_oauth2_custom_state(),
        settings=get_settings(),
        expected_user_id="user-1",
        expected_provider=get_settings().m365_calendar_provider_name,
    )
    assert claims.session_id == "sess-abc"


# ---------------------------------------------------------------------------
# Header handling tests
# ---------------------------------------------------------------------------


class TestHeaderHandling:
    """Verify the /invocations endpoint reads AgentArts Gateway headers.

    - session_id: from SESSION_HEADER (400 if missing)
    - user_id: from USER_ID_HEADER (fail-closed: 401 if missing)
    - workload_access_token: from ACCESS_TOKEN_HEADER (silent no-op if missing)
    """

    # ── session_id ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_session_id_from_official_header(self, client, fake_handler):
        """SESSION_HEADER is recognized."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                USER_ID_HEADER: "test-user",
                SESSION_HEADER: "sess-123",
            },
        )
        assert fake_handler.handle_calls[0][2] == "sess-123"

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_400(self, client):
        """POST /invocations without SESSION_HEADER returns 400."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={USER_ID_HEADER: "test-user"},
        )
        assert response.status_code == 400
        assert SESSION_HEADER in response.json()["detail"]

    # ── user_id ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_user_id_from_official_gateway_header(self, client, fake_handler):
        """USER_ID_HEADER is recognized."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                USER_ID_HEADER: "user-x",
                SESSION_HEADER: "sess-test",
            },
        )
        assert fake_handler.handle_calls[0][1] == "user-x"

    @pytest.mark.asyncio
    async def test_invocations_gateway_user_id_passed_to_handler(
        self, client, fake_handler
    ):
        """POST with USER_ID_HEADER: special-user →
        handler receives user_id='special-user'."""
        await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={
                USER_ID_HEADER: "special-user",
                SESSION_HEADER: "sess-test",
            },
        )
        assert fake_handler.handle_calls[0][1] == "special-user"

    @pytest.mark.asyncio
    async def test_user_id_anonymous_default(self, client):
        """No user-id header → fail-closed with 401."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={SESSION_HEADER: "sess-default"},
        )
        assert response.status_code == 401
        assert USER_ID_HEADER in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_invocations_missing_gateway_user_id_returns_401(self, client):
        """POST /invocations with valid session_id but no user-id header → 401."""
        response = await client.post(
            "/invocations",
            json={"message": "Hi"},
            headers={SESSION_HEADER: "sess-test"},
        )
        assert response.status_code == 401
        assert USER_ID_HEADER in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_workload_token_passed_to_context(self, client, fake_handler):
        """POST with workload token header → SDK context receives the token."""
        token_value = "test-token-abc123"
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            response = await client.post(
                "/invocations",
                json={"message": "Hi"},
                headers={
                    USER_ID_HEADER: "test-user",
                    SESSION_HEADER: "sess-test",
                    ACCESS_TOKEN_HEADER: token_value,
                },
            )
            assert response.status_code == 200
            mock_set.assert_called_once_with(token_value)

    @pytest.mark.asyncio
    async def test_no_workload_token_no_error(self, client, fake_handler):
        """POST without workload token header → 200, SDK context gets None."""
        with patch(
            "app.auth.AgentArtsRuntimeContext.set_workload_access_token"
        ) as mock_set:
            response = await client.post(
                "/invocations",
                json={"message": "Hi"},
                headers={
                    USER_ID_HEADER: "test-user",
                    SESSION_HEADER: "sess-test",
                },
            )
            assert response.status_code == 200
            mock_set.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_invocations_stream_false_returns_response(client, fake_handler):
    """POST /invocations with stream=false keeps synchronous behavior."""
    response = await client.post(
        "/invocations",
        json={"message": "Hello, assistant!", "stream": False},
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
async def test_invocations_whitespace_only_returns_400(client, fake_handler):
    """Whitespace-only messages are rejected consistently in sync mode."""
    response = await client.post(
        "/invocations",
        json={"message": "   "},
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "message is required"
    assert fake_handler.handle_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", ["false", "true", 0, 1, None])
async def test_invocations_rejects_non_boolean_stream(client, fake_handler, stream):
    """The stream selector accepts JSON booleans only."""
    response = await client.post(
        "/invocations",
        json={"message": "Hello", "stream": stream},
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "stream must be a boolean"
    assert fake_handler.handle_calls == []
    assert fake_handler.stream_calls == []


@pytest.mark.asyncio
async def test_invocations_rejects_non_object_body(client):
    """The request body must be a JSON object."""
    response = await client.post(
        "/invocations",
        json=["not", "an", "object"],
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid request body"


@pytest.mark.asyncio
async def test_invocations_rejects_non_string_message(client):
    """The message field accepts strings only."""
    response = await client.post(
        "/invocations",
        json={"message": 123},
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "message must be a string"


@pytest.mark.asyncio
async def test_invocations_sync_rejects_incompatible_accept(client, fake_handler):
    """Sync invocations reject an Accept header that excludes JSON."""
    response = await client.post(
        "/invocations",
        json={"message": "Hello"},
        headers={
            "Accept": "text/event-stream",
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 406
    assert response.json()["detail"] == "Accept header must allow application/json"
    assert fake_handler.handle_calls == []


# ---------------------------------------------------------------------------
# App startup validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_llm_provider_causes_startup_error(monkeypatch):
    """App lifespan fails fast when the canonical Provider is unknown."""
    from fastapi import FastAPI

    from app.main import lifespan
    from app.settings import Settings

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
            USER_ID_HEADER: "user-1",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert "text/event-stream" in content_type, f"Got: {content_type}"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["connection"] == "keep-alive"
    assert fake_handler.stream_calls[0][:3] == ("hello", "user-1", "sess-test")

    # Verify the stream call preserves message and identity context.
    call_args = fake_handler.stream_calls[0]
    assert call_args[0] == "hello"
    assert call_args[1] == "user-1"
    assert call_args[2] == "sess-test"

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
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
async def test_invocations_stream_rejects_incompatible_accept(client, fake_handler):
    """Streaming invocations reject an Accept header that excludes SSE."""
    response = await client.post(
        "/invocations",
        json={"message": "hello", "stream": True},
        headers={
            "Accept": "application/json",
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 406
    assert response.json()["detail"] == "Accept header must allow text/event-stream"
    assert fake_handler.stream_calls == []


@pytest.mark.asyncio
async def test_invocations_logs_selected_mode(client):
    """Invocation logs distinguish sync and stream traffic."""
    headers = {
        USER_ID_HEADER: "test-user",
        SESSION_HEADER: "sess-test",
    }
    with patch("app.main.logger.info") as mock_info:
        await client.post("/invocations", json={"message": "hello"}, headers=headers)
        await client.post(
            "/invocations",
            json={"message": "hello", "stream": True},
            headers=headers,
        )

    mock_info.assert_any_call("Invocation started mode=%s", "sync")
    mock_info.assert_any_call(
        "Invocation completed mode=sync status=success duration_ms=%.2f",
        ANY,
    )
    mock_info.assert_any_call("Invocation started mode=%s", "stream")
    mock_info.assert_any_call(
        "Invocation completed mode=stream status=%s duration_ms=%.2f",
        "success",
        ANY,
    )


@pytest.mark.asyncio
async def test_invocations_stream_empty_message_returns_400(client):
    """POST /invocations with stream=true and empty message returns 400."""
    response = await client.post(
        "/invocations",
        json={"message": "", "stream": True},
        headers={
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
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
            USER_ID_HEADER: "test-user",
            SESSION_HEADER: "sess-test",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_old_invocations_stream_route_returns_404(client):
    """GET /invocations/stream remains removed after route consolidation."""
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
