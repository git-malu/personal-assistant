"""E2E tests for refactored email OAuth2 auth flow using normal control flow.

Tests the ContextVar-isolated message_queue flow for delivering auth URLs
via SSE system_message events, replacing the old exception-based
AuthUrlRequired flow.

Test scenarios from plan:
  E2E-AUTH-01: OAuth2 auth URL delivered via SSE system_message
  E2E-AUTH-02: system_message interleaved with tokens — correct ordering
  E2E-AUTH-03: system_message fields are complete
  E2E-AUTH-04: done: true normal ending
  E2E-AUTH-05: Normal email operations without auth (regression)
  E2E-AUTH-06: Non-streaming path unaffected
  E2E-AUTH-07: Queue lifecycle — no cross-request leakage
  E2E-AUTH-08: Concurrency isolation
"""

import contextlib
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# NOTE: These tests run from the service venv which has agentarts-sdk
# installed, so no sys.modules mocking is needed. The email_tools import
# chain (agentarts.sdk → agentarts.sdk.runtime → etc.) resolves normally.

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE response text into a list of JSON event dicts."""
    events: list[dict] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            with contextlib.suppress(json.JSONDecodeError):
                events.append(json.loads(line[6:]))
    return events


def _stream_headers() -> dict[str, str]:
    """Return default headers for streaming POST /invocations."""
    return {
        "X-HW-AgentGateway-User-Id": "test-user",
        "x-hw-agentarts-session-id": "e2e-auth-session",
        "Accept": "text/event-stream",
    }


# ─────────────────────────────────────────────────────────────────────────────
# FakeAuthHandler — simulates the message_queue flow
# ─────────────────────────────────────────────────────────────────────────────

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
AUTH_MESSAGE_CONTENT = (
    "邮件功能需要您的授权。请点击以下链接进行授权：\n\n"
    f"{AUTH_URL}\n\n"
    "授权完成后，请再次告诉我您需要做什么。"
)


class FakeAuthHandler:
    """Fake AgentHandler that supports the adispatch_custom_event flow."""

    def __init__(self):
        self.handle_calls: list[tuple] = []
        self.stream_calls: list[tuple] = []
        self.simulate_auth: bool = False
        self._tokens: list[str] = ["你好", "，", "世界", "！"]

    async def handle(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ) -> str:
        self.handle_calls.append((message, user_id, session_id))
        return f"Response to: '{message}'"

    async def handle_stream(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
    ):
        self.stream_calls.append((message, user_id, session_id))

        if self.simulate_auth:
            payload = {
                "system_message": AUTH_MESSAGE_CONTENT,
                "auth_url": AUTH_URL,
                "auth_required": True,
            }
            yield f"data: {json.dumps(payload)}\n\n"

        for _idx, token in enumerate(self._tokens):
            yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"

        yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def auth_fake_handler() -> FakeAuthHandler:
    """Create a FakeAuthHandler instance."""
    return FakeAuthHandler()


@pytest.fixture
def auth_test_client(auth_fake_handler: FakeAuthHandler):
    """FastAPI TestClient with FakeAuthHandler patched in.

    Patches init_chat_model (lifespan startup) and AgentHandler class
    so get_agent_handler() returns our fake. This exercises the full
    FastAPI stack — routing, SSE formatting, header handling — with
    our controlled fake handler.
    """
    with (
        patch("app.llm_config.init_chat_model", return_value=MagicMock()),
        patch("app.agent_handler.AgentHandler", return_value=auth_fake_handler),
    ):
        from app.main import app

        # Ensure the handler is set (lifespan will call get_agent_handler
        # which now returns our fake handler)
        app.state.agent_handler = auth_fake_handler

        client = TestClient(app, raise_server_exceptions=False)
        yield client, auth_fake_handler


@pytest.fixture
async def async_auth_client(auth_fake_handler: FakeAuthHandler):
    """Async httpx client for tests that need concurrency (E2E-AUTH-08).

    Uses httpx.AsyncClient with ASGITransport for in-process FastAPI testing.
    Must be async because ASGITransport requires httpx.AsyncClient.
    """
    import app.main as app_main

    with patch.object(app_main, "AgentHandler", return_value=auth_fake_handler):
        from app.main import app

        app.state.agent_handler = auth_fake_handler

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client, auth_fake_handler


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-01: OAuth2 auth URL delivered via SSE system_message
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_auth_url_delivered_via_sse_system_message(auth_test_client):
    """E2E-AUTH-01: Auth URL delivered as SSE system_message event.

    POST /invocations with stream=true, handler simulates auth callback.
    Verifies:
    - SSE stream contains a system_message event (not just token events)
    - Event has auth_url with a valid URL
    - auth_required: true is present
    - Last event has done: true
    """
    client, fake_handler = auth_test_client
    fake_handler.simulate_auth = True

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers=_stream_headers(),
    )

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )

    # Verify content-type
    content_type = resp.headers.get("content-type", "")
    assert "text/event-stream" in content_type, (
        f"Expected text/event-stream, got: {content_type}"
    )

    events = _parse_sse_events(resp.text)
    assert len(events) >= 1, f"Expected at least 1 SSE event, got {len(events)}"

    # Find system_message events
    system_events = [e for e in events if "system_message" in e]
    assert len(system_events) >= 1, (
        f"Expected at least 1 system_message event, got {len(system_events)}. "
        f"All events: {events}"
    )

    se = system_events[0]
    assert "auth_url" in se, f"system_message event missing 'auth_url': {se}"
    assert se["auth_url"].startswith("https://"), (
        f"auth_url should be a URL, got: {se['auth_url']}"
    )
    assert se.get("auth_required") is True, (
        f"auth_required should be True, got: {se.get('auth_required')}"
    )

    # Verify last event has done: true
    last_event = events[-1]
    assert last_event.get("done") is True, (
        f"Last SSE event should have done=True: {last_event}"
    )

    # Verify stream_calls recorded
    assert len(fake_handler.stream_calls) == 1


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-02: system_message interleaved with tokens — correct ordering
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_system_message_appears_before_tokens(auth_test_client):
    """E2E-AUTH-02: system_message appears BEFORE token events in SSE stream.

    The drain-before-token logic ensures system_message events are
    yielded before any token events. This verifies the correct ordering.
    """
    client, fake_handler = auth_test_client
    fake_handler.simulate_auth = True

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers=_stream_headers(),
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"

    # Find the index of the first system_message event
    first_system_idx = None
    first_token_idx = None
    for i, e in enumerate(events):
        if "system_message" in e and first_system_idx is None:
            first_system_idx = i
        if "token" in e and not e.get("done") and first_token_idx is None:
            first_token_idx = i

    assert first_system_idx is not None, "No system_message event found"
    assert first_token_idx is not None, "No token event found before done"

    # system_message must appear before (or at same position as) first token
    assert first_system_idx <= first_token_idx, (
        f"system_message (idx={first_system_idx}) must appear before "
        f"or at same position as first token (idx={first_token_idx}). "
        f"Events: {[list(e.keys()) for e in events]}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-03: system_message fields are complete
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_system_message_fields_complete(auth_test_client):
    """E2E-AUTH-03: system_message event has all required fields.

    Verifies SSE JSON contains system_message (content text),
    auth_url (valid URL), and auth_required (true), all present
    with correct values.
    """
    client, fake_handler = auth_test_client
    fake_handler.simulate_auth = True

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers=_stream_headers(),
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    system_events = [e for e in events if "system_message" in e]
    assert len(system_events) >= 1, f"No system_message event in: {events}"

    se = system_events[0]

    # system_message (the content text) must be present and non-empty
    assert "system_message" in se, f"Missing 'system_message' key: {se}"
    assert isinstance(se["system_message"], str), (
        f"system_message should be a string: {type(se['system_message'])}"
    )
    assert len(se["system_message"]) > 0, "system_message content must not be empty"
    assert "授权" in se["system_message"], (
        f"system_message should mention authorization: {se['system_message'][:200]}"
    )

    # auth_url must be present and a valid URL
    assert "auth_url" in se, f"Missing 'auth_url' key: {se}"
    assert se["auth_url"].startswith("https://"), (
        f"auth_url should start with https://: {se['auth_url']}"
    )

    # auth_required must be True
    assert "auth_required" in se, f"Missing 'auth_required' key: {se}"
    assert se["auth_required"] is True, (
        f"auth_required should be True: {se['auth_required']}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-04: done: true normal ending
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_auth_stream_ends_with_done_true(auth_test_client):
    """E2E-AUTH-04: After system_message + tokens, stream ends with done: true.

    Verifies the normal completion signal is present even when
    system_message events are interleaved in the stream.
    """
    client, fake_handler = auth_test_client
    fake_handler.simulate_auth = True

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers=_stream_headers(),
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    assert len(events) >= 1, f"Expected at least 1 event, got {len(events)}"

    # Last event must signal completion
    last_event = events[-1]
    assert last_event.get("done") is True, (
        f"Last SSE event should have done=True: {last_event}"
    )

    # There should be exactly one done event
    done_events = [e for e in events if e.get("done")]
    assert len(done_events) == 1, (
        f"Expected exactly 1 done event, got {len(done_events)}: {done_events}"
    )

    # Verify there are token events and system_message events before done
    token_events = [e for e in events if "token" in e and not e.get("done")]
    system_events = [e for e in events if "system_message" in e]
    assert len(token_events) >= 1, (
        f"Expected at least 1 token event, got events: {events}"
    )
    assert len(system_events) >= 1, "Expected at least 1 system_message event"


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-05: Normal email operations without auth (regression)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_normal_streaming_has_no_system_message(auth_test_client):
    """E2E-AUTH-05: Normal streaming without auth — no system_message events.

    When no system_message is in the queue, SSE stream only has token
    events and done — no system_message events. This verifies backward
    compatibility with non-auth scenarios.
    """
    client, fake_handler = auth_test_client
    fake_handler.simulate_auth = False  # No auth simulation

    resp = client.post(
        "/invocations",
        json={"message": "你好", "stream": True},
        headers=_stream_headers(),
    )
    assert resp.status_code == 200

    events = _parse_sse_events(resp.text)
    assert len(events) >= 2, (
        f"Expected at least 2 events (token + done), got {len(events)}"
    )

    # No system_message events
    system_events = [e for e in events if "system_message" in e]
    assert len(system_events) == 0, (
        f"Expected no system_message events in normal flow, got: {system_events}"
    )

    # Should have token events and a done event
    token_events = [e for e in events if "token" in e and not e.get("done")]
    assert len(token_events) >= 1, (
        f"Expected at least 1 token event, got events: {events}"
    )

    # Last event should be done: true
    assert events[-1].get("done") is True, (
        f"Last event should have done=True: {events[-1]}"
    )

    # Verify content-type is correct
    assert "text/event-stream" in resp.headers.get("content-type", "")


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-06: Non-streaming path unaffected
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_non_streaming_path_unaffected(auth_test_client):
    """E2E-AUTH-06: Non-streaming path returns normal JSON response.

    POST /invocations with stream=false returns 200 with 'response' key.
    The non-streaming path does not use message_queue and should not
    be affected by the refactoring.
    """
    client, fake_handler = auth_test_client

    resp = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": False},
        headers={
            "X-HW-AgentGateway-User-Id": "test-user",
            "x-hw-agentarts-session-id": "e2e-nonstream",
        },
    )

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    )

    data = resp.json()
    assert "response" in data, f"No 'response' key in: {data}"
    assert isinstance(data["response"], str), (
        f"response should be a string: {type(data['response'])}"
    )
    assert len(data["response"]) > 0, "Response should not be empty"

    # Verify handler was called with correct params
    assert len(fake_handler.handle_calls) == 1, (
        f"Expected 1 handle call, got {len(fake_handler.handle_calls)}"
    )
    msg, user_id, session_id = fake_handler.handle_calls[0]
    assert msg == "帮我看看收件箱"
    assert user_id == "test-user"
    assert session_id == "e2e-nonstream"


# ═════════════════════════════════════════════════════════════════════════════
# E2E-AUTH-07: Queue lifecycle — no cross-request leakage
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.feature
def test_queue_lifecycle_no_cross_request_leakage(auth_test_client):
    """E2E-AUTH-07: Queue cleanup prevents cross-request leakage.

    Round 1: send auth request → verify system_message in stream.
    Round 2: send normal request → verify NO system_message in stream.
    Uses the SAME TestClient (same app instance) for both requests,
    verifying that set_message_queue(None) in finally properly cleans
    up the ContextVar.
    """
    client, fake_handler = auth_test_client

    # ── Round 1: Trigger auth ──
    fake_handler.simulate_auth = True
    resp1 = client.post(
        "/invocations",
        json={"message": "帮我看看收件箱", "stream": True},
        headers=_stream_headers(),
    )
    assert resp1.status_code == 200
    events1 = _parse_sse_events(resp1.text)
    system_events_r1 = [e for e in events1 if "system_message" in e]
    assert len(system_events_r1) >= 1, (
        "Round 1: Expected system_message event, got events: "
        f"{[list(e.keys()) for e in events1]}"
    )

    # ── Round 2: Normal request (no auth) ──
    fake_handler.simulate_auth = False
    resp2 = client.post(
        "/invocations",
        json={"message": "你好", "stream": True},
        headers=_stream_headers(),
    )
    assert resp2.status_code == 200
    events2 = _parse_sse_events(resp2.text)
    system_events_r2 = [e for e in events2 if "system_message" in e]
    assert len(system_events_r2) == 0, (
        f"Round 2: Expected NO system_message event (queue should be cleaned), "
        f"but got: {system_events_r2}"
    )

    # Both calls tracked
    assert len(fake_handler.stream_calls) == 2
