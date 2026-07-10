"""Service integration coverage extracted from mixed Web Chat E2E tests."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from agentarts.sdk.runtime.model import SESSION_HEADER, USER_ID_HEADER

SERVICE_DIR = Path(__file__).resolve().parents[2]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

pytestmark = [pytest.mark.integration]


class FakeWebChatAgentHandler:
    """Predictable Agent handler for Web Chat invocation route tests."""

    def __init__(self, tokens: list[str] | None = None):
        self._tokens = tokens or ["Hello", " world", "!"]
        self.handle_calls: list[tuple[str, str, str | None]] = []
        self.stream_calls: list[tuple[str, str, str | None]] = []

    async def handle(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str | None = None,
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
            yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
        yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"


@pytest.fixture
def fake_handler():
    return FakeWebChatAgentHandler()


@pytest.fixture
async def web_chat_client(fake_handler):
    from app.main import app

    had_previous_handler = hasattr(app.state, "agent_handler")
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.agent_handler = fake_handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    if had_previous_handler:
        app.state.agent_handler = previous_handler
    elif hasattr(app.state, "agent_handler"):
        delattr(app.state, "agent_handler")


def _headers(session_id: str = "web-chat-session") -> dict[str, str]:
    return {
        USER_ID_HEADER: "web-chat-user",
        SESSION_HEADER: session_id,
    }


async def _post_stream(client: httpx.AsyncClient, message: str) -> httpx.Response:
    return await client.post(
        "/invocations",
        json={"message": message, "stream": True},
        headers={
            **_headers(),
            "Accept": "text/event-stream",
        },
    )


def _sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestWebChatInvocationStreaming:
    """Service-owned SSE contract for Web Chat invocations."""

    @pytest.mark.asyncio
    async def test_sse_content_type_and_headers(self, web_chat_client):
        resp = await _post_stream(web_chat_client, "Hello")

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("connection") == "keep-alive"
        assert resp.headers.get("x-accel-buffering") == "no"

    @pytest.mark.asyncio
    async def test_sse_data_prefix_format(self, web_chat_client):
        resp = await _post_stream(web_chat_client, "Hello")

        assert resp.status_code == 200
        lines = [line for line in resp.text.splitlines() if line.strip()]
        assert lines
        assert all(line.startswith("data: ") for line in lines)
        assert all("token" in json.loads(line[6:]) for line in lines)

    @pytest.mark.asyncio
    async def test_sse_streams_multiple_events(self, web_chat_client, fake_handler):
        resp = await _post_stream(web_chat_client, "Hello")

        assert resp.status_code == 200
        events = _sse_events(resp.text)
        tokens = [event for event in events if not event.get("done")]
        done_events = [event for event in events if event.get("done")]
        assert len(tokens) >= 1
        assert len(done_events) == 1
        assert done_events[0]["done"] is True
        assert fake_handler.stream_calls == [
            ("Hello", "web-chat-user", "web-chat-session")
        ]

    @pytest.mark.asyncio
    async def test_sse_with_chinese_text(self, web_chat_client):
        resp = await _post_stream(web_chat_client, "你好世界")

        assert resp.status_code == 200
        assert _sse_events(resp.text)

    @pytest.mark.asyncio
    async def test_sse_with_special_characters(self, web_chat_client):
        resp = await _post_stream(web_chat_client, "Hello!+@#$%")

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


class TestWebChatMultiTurnConversation:
    """Sequential request behavior belongs to the Service invocation contract."""

    @pytest.mark.asyncio
    async def test_multiple_messages_return_valid_sse(
        self, web_chat_client, fake_handler
    ):
        messages = ["Hello", "How are you?", "What time is it?"]

        for message in messages:
            resp = await _post_stream(web_chat_client, message)
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            assert len(_sse_events(resp.text)) >= 2

        assert [call[0] for call in fake_handler.stream_calls] == messages

    @pytest.mark.asyncio
    async def test_rapid_successive_requests_no_crash(self, web_chat_client):
        for i in range(10):
            resp = await _post_stream(web_chat_client, f"msg{i}")
            assert resp.status_code == 200


class TestWebChatInvocationValidation:
    """Validation behavior for invalid Web Chat invocation payloads."""

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self, web_chat_client, fake_handler):
        resp = await web_chat_client.post(
            "/invocations",
            json={"message": "", "stream": True},
            headers=_headers(),
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "message is required"
        assert fake_handler.stream_calls == []

    @pytest.mark.asyncio
    async def test_missing_message_returns_400(self, web_chat_client, fake_handler):
        resp = await web_chat_client.post(
            "/invocations",
            json={"stream": True},
            headers=_headers(),
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "message is required"
        assert fake_handler.stream_calls == []

    @pytest.mark.asyncio
    async def test_whitespace_only_message_returns_400(
        self, web_chat_client, fake_handler
    ):
        resp = await web_chat_client.post(
            "/invocations",
            json={"message": "  ", "stream": True},
            headers=_headers(),
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "message is required"
        assert fake_handler.stream_calls == []

    @pytest.mark.asyncio
    async def test_service_does_not_crash_after_invalid_request(self, web_chat_client):
        bad_resp = await web_chat_client.post(
            "/invocations",
            json={"message": "", "stream": True},
            headers=_headers(),
        )
        good_resp = await _post_stream(web_chat_client, "valid")

        assert bad_resp.status_code == 400
        assert good_resp.status_code == 200
        assert _sse_events(good_resp.text)
