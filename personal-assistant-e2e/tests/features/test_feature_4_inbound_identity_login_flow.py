"""E2E tests for Feature 4 — Inbound Identity: dev-mode login flow.

Tests the happy path with dev-mode identity injection:
- Valid X-HW-AgentGateway-User-Id header → 200 OK
- Streaming invocation with valid identity
- Service continues working after valid auth
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Fake AgentHandler ────────────────────────────────────────────────────


class FakeAgentHandler:
    """A fake AgentHandler with predictable streaming/non-streaming responses."""

    def __init__(self, tokens: list[str] | None = None):
        self._tokens = tokens or ["Hello", " from", " mock", " agent", "!"]
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        return "".join(self._tokens)

    async def handle_stream(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ):
        self.stream_calls.append((message, user_id, session_id))
        for token in self._tokens:
            yield f'data: {json.dumps({"token": token, "done": False})}\n\n'
        yield f'data: {json.dumps({"token": "", "done": True})}\n\n'


# ── Test Fixture ─────────────────────────────────────────────────────────


@pytest.fixture
def identity_test_client():
    """Create FastAPI TestClient with mocked LLM config and FakeAgentHandler.

    Mocks init_chat_model (for lifespan startup) and AgentHandler class
    (so get_agent_handler() returns our fake handler). This allows testing
    the full FastAPI stack including auth layer without real LLM calls.
    """
    os.environ.setdefault("MAAS_API_KEY", "dummy-e2e-test-key")

    fake_handler = FakeAgentHandler()

    with patch("app.llm_config.init_chat_model", return_value=MagicMock()), patch(
        "app.agent_handler.AgentHandler", return_value=fake_handler
    ):
        from app.main import app

        # Ensure the handler is set (lifespan will call get_agent_handler
        # which now returns our fake handler)
        app.state.agent_handler = fake_handler

        client = TestClient(app, raise_server_exceptions=False)
        yield client, fake_handler


# ── Scenario 1: Valid user_id → 200 OK (non-streaming) ───────────────────


@pytest.mark.feature
def test_invocations_with_valid_gateway_user_id(identity_test_client):
    """POST /invocations with valid X-HW-AgentGateway-User-Id returns 200."""
    client, fake_handler = identity_test_client

    resp = client.post(
        "/invocations",
        json={"message": "Hello"},
        headers={
            "X-HW-AgentGateway-User-Id": "dev-user",
            "x-hw-agentarts-session-id": "test-session-e2e",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )

    # Verify the fake handler was called with the correct user_id
    assert len(fake_handler.handle_calls) == 1, (
        f"Expected 1 handle call, got {len(fake_handler.handle_calls)}"
    )
    msg, user_id, session_id = fake_handler.handle_calls[0]
    assert msg == "Hello"
    assert user_id == "dev-user", (
        f"Expected user_id='dev-user', got {user_id!r}"
    )
    assert session_id == "test-session-e2e", (
        f"Expected session_id='test-session-e2e', got {session_id!r}"
    )

    # Verify response body
    data = resp.json()
    assert "response" in data, f"No 'response' key in: {data}"
    assert len(data["response"]) > 0, "Response should not be empty"


# ── Scenario 2: Streaming invocation with valid identity ───────────────


@pytest.mark.feature
def test_streaming_invocation_with_valid_user_id(identity_test_client):
    """POST /invocations stream=true with valid identity returns SSE."""
    client, fake_handler = identity_test_client

    resp = client.post(
        "/invocations",
        json={"message": "Hello", "stream": True},
        headers={
            "X-HW-AgentGateway-User-Id": "dev-user",
            "x-hw-agentarts-session-id": "test-session-e2e",
            "Accept": "text/event-stream",
        },
    )
    assert resp.status_code == 200, (
        f"Expected 200 for streaming, got {resp.status_code}: {resp.text[:300]}"
    )

    # Verify content-type is SSE
    content_type = resp.headers.get("content-type", "")
    assert "text/event-stream" in content_type, (
        f"Expected text/event-stream content-type, got: {content_type}"
    )

    # Verify SSE headers
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("connection") == "keep-alive"

    # Verify stream_calls recorded with correct user_id
    assert len(fake_handler.stream_calls) == 1, (
        f"Expected 1 stream call, got {len(fake_handler.stream_calls)}"
    )
    msg, user_id, session_id = fake_handler.stream_calls[0]
    assert msg == "Hello"
    assert user_id == "dev-user", (
        f"Expected user_id='dev-user' in stream call, got {user_id!r}"
    )

    # Verify SSE format
    body = resp.text
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    assert len(lines) > 0, "SSE response should have data lines"

    for line in lines:
        assert line.startswith("data: "), (
            f"SSE line should start with 'data: ': {line[:80]}"
        )
        payload = line[6:]  # strip "data: " prefix
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON in SSE: {payload[:100]}")
        assert "done" in data, f"SSE data missing 'done' field: {data}"

    # Last event should have done=True
    last_event = json.loads(lines[-1][6:])
    assert last_event["done"] is True, (
        f"Last SSE event should have done=True: {last_event}"
    )


# ── Scenario 3: Service continues after valid auth ──────────────────────


@pytest.mark.feature
def test_multiple_requests_with_same_user_id(identity_test_client):
    """Multiple requests with same valid user_id all succeed."""
    client, fake_handler = identity_test_client

    headers = {
        "X-HW-AgentGateway-User-Id": "dev-user",
        "x-hw-agentarts-session-id": "test-multi",
    }

    for i in range(3):
        resp = client.post(
            "/invocations",
            json={"message": f"Message {i}"},
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"Request {i}: expected 200, got {resp.status_code}: {resp.text[:200]}"
        )

    assert len(fake_handler.handle_calls) == 3
    for i, (msg, uid, _sid) in enumerate(fake_handler.handle_calls):
        assert msg == f"Message {i}"
        assert uid == "dev-user"


# ── Scenario 4: Different user_ids work independently ──────────────────


@pytest.mark.feature
def test_different_user_ids_accepted(identity_test_client):
    """Different X-HW-AgentGateway-User-Id values are all accepted."""
    client, fake_handler = identity_test_client

    headers_a = {
        "X-HW-AgentGateway-User-Id": "user-a",
        "x-hw-agentarts-session-id": "session-a",
    }
    headers_b = {
        "X-HW-AgentGateway-User-Id": "user-b",
        "x-hw-agentarts-session-id": "session-b",
    }

    resp_a = client.post("/invocations", json={"message": "msg-a"}, headers=headers_a)
    assert resp_a.status_code == 200, f"User A failed: {resp_a.status_code}"

    resp_b = client.post("/invocations", json={"message": "msg-b"}, headers=headers_b)
    assert resp_b.status_code == 200, f"User B failed: {resp_b.status_code}"

    # Verify correct user_ids were passed to handler
    assert len(fake_handler.handle_calls) == 2
    _, uid_a, sid_a = fake_handler.handle_calls[0]
    _, uid_b, sid_b = fake_handler.handle_calls[1]
    assert uid_a == "user-a"
    assert uid_b == "user-b"
    assert sid_a == "session-a"
    assert sid_b == "session-b"


# ── Scenario 5: Missing session-id → 400 (not 401) ─────────────────────


@pytest.mark.feature
def test_invocations_with_valid_user_id_but_missing_session_id(identity_test_client):
    """POST /invocations with valid user_id but missing session-id returns 400,
    NOT 401 — proving auth passes but session validation fails after."""
    client, _ = identity_test_client

    resp = client.post(
        "/invocations",
        json={"message": "Hello"},
        headers={"X-HW-AgentGateway-User-Id": "dev-user"},
        # intentionally no x-hw-agentarts-session-id
    )
    # Should be 400 (session-id missing), not 401 (auth failed)
    assert resp.status_code == 400, (
        f"Expected 400 for missing session-id, "
        f"got {resp.status_code}: {resp.text[:200]}"
    )
    data = resp.json()
    assert "x-hw-agentarts-session-id" in data.get("detail", ""), (
        f"Expected 'x-hw-agentarts-session-id' in error detail, got: {data}"
    )


# ── Scenario 6: Empty message with valid auth → 400 ────────────────────


@pytest.mark.feature
def test_invocations_with_valid_auth_empty_message_returns_400(identity_test_client):
    """POST /invocations with valid auth but empty message returns 400,
    NOT 401 — proving auth passes but validation fails at message check."""
    client, _ = identity_test_client

    resp = client.post(
        "/invocations",
        json={"message": ""},
        headers={
            "X-HW-AgentGateway-User-Id": "dev-user",
            "x-hw-agentarts-session-id": "test-session",
        },
    )
    assert resp.status_code == 400, (
        f"Expected 400 for empty message, got {resp.status_code}: {resp.text[:200]}"
    )
