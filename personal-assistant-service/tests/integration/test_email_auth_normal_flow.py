from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from agentarts.sdk.runtime.model import ACCESS_TOKEN_HEADER, SESSION_HEADER
from alembic import command
from alembic.config import Config

from app.conversations.store import ConversationRecord, ConversationStore
from app.database import Database
from app.invocations.models import AgentEventType, AgentStreamEvent
from app.main import app
from tests.conftest import PostgresTestSchema

SERVICE_ROOT = Path(__file__).resolve().parents[2]
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
AUTH_CARD_DATA = {
    "type": "system_message",
    "system_message": "邮件功能需要您的授权。请点击该链接进行授权",
    "auth_url": AUTH_URL,
    "auth_required": True,
    "provider": "m365-email-provider",
}
CUSTOM_EVENT_DATA = {"type": "email_progress", "status": "waiting_for_auth"}


class FakeAuthHandler:
    def __init__(self) -> None:
        self.stream_events = [
            AgentStreamEvent(type=AgentEventType.TOKEN, token="你好"),
            AgentStreamEvent(type=AgentEventType.TOKEN, token="，世界"),
        ]
        self.stream_calls: list[tuple[str, str, str]] = []

    async def handle_stream(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        self.stream_calls.append((message, user_id, conversation_id))
        for event in self.stream_events:
            yield event


@dataclass
class AuthInvocationContext:
    client: httpx.AsyncClient
    handler: FakeAuthHandler
    store: ConversationStore


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.signature"


def _headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject)}",
        ACCESS_TOKEN_HEADER: "gateway-workload-token",
        SESSION_HEADER: "email-auth-session",
        "Accept": "text/event-stream",
    }


def _payload(
    conversation: ConversationRecord,
    *,
    message: str,
    client_message_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "conversation_id": str(conversation.id),
        "client_message_id": str(client_message_id or uuid4()),
        "message": message,
        "stream": True,
    }


def _parse_sse_frames(
    text: str,
) -> list[tuple[str | None, dict[str, object]]]:
    frames: list[tuple[str | None, dict[str, object]]] = []
    normalized = text.replace("\r\n", "\n").strip()
    for block in normalized.split("\n\n"):
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if data_lines:
            frames.append((event_name, json.loads("\n".join(data_lines))))
    return frames


@pytest.fixture
async def auth_invocation_context(
    postgres_schema: PostgresTestSchema,
) -> AsyncIterator[AuthInvocationContext]:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")

    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
    )
    await database.startup()
    handler = FakeAuthHandler()
    previous_database = getattr(app.state, "database", None)
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.database = database
    app.state.agent_handler = handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield AuthInvocationContext(
                client=client,
                handler=handler,
                store=ConversationStore(database),
            )
        finally:
            if previous_database is None:
                delattr(app.state, "database")
            else:
                app.state.database = previous_database
            if previous_handler is None:
                delattr(app.state, "agent_handler")
            else:
                app.state.agent_handler = previous_handler
            await database.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_auth_card_custom_and_token_events_keep_wire_order(
    auth_invocation_context: AuthInvocationContext,
):
    context = auth_invocation_context
    conversation = await context.store.create(user_id="user-1", title="Email auth")
    context.handler.stream_events = [
        AgentStreamEvent(type=AgentEventType.TOKEN, token="授权前"),
        AgentStreamEvent(type=AgentEventType.AUTH_CARD, data=AUTH_CARD_DATA),
        AgentStreamEvent(type=AgentEventType.CUSTOM, data=CUSTOM_EVENT_DATA),
        AgentStreamEvent(type=AgentEventType.TOKEN, token="授权后"),
    ]

    response = await context.client.post(
        "/invocations",
        json=_payload(conversation, message="帮我看看收件箱"),
        headers=_headers("user-1"),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert _parse_sse_frames(response.text) == [
        (None, {"token": "授权前", "done": False}),
        ("auth_card", AUTH_CARD_DATA),
        (None, CUSTOM_EVENT_DATA),
        (None, {"token": "授权后", "done": False}),
        (None, {"token": "", "done": True}),
    ]
    assert context.handler.stream_calls == [
        ("帮我看看收件箱", "user-1", str(conversation.id))
    ]

    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content.parts[0].text == "授权前授权后"
    assert AUTH_URL not in messages[1].content.parts[0].text


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_normal_email_stream_contains_only_tokens_and_success_terminal(
    auth_invocation_context: AuthInvocationContext,
):
    context = auth_invocation_context
    conversation = await context.store.create(user_id="user-1", title="Normal email")

    response = await context.client.post(
        "/invocations",
        json=_payload(conversation, message="总结最新邮件"),
        headers=_headers("user-1"),
    )

    assert response.status_code == 200
    assert _parse_sse_frames(response.text) == [
        (None, {"token": "你好", "done": False}),
        (None, {"token": "，世界", "done": False}),
        (None, {"token": "", "done": True}),
    ]


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_auth_events_do_not_leak_into_the_next_request(
    auth_invocation_context: AuthInvocationContext,
):
    context = auth_invocation_context
    conversation = await context.store.create(user_id="user-1", title="No leakage")
    context.handler.stream_events = [
        AgentStreamEvent(type=AgentEventType.AUTH_CARD, data=AUTH_CARD_DATA),
        AgentStreamEvent(type=AgentEventType.CUSTOM, data=CUSTOM_EVENT_DATA),
        AgentStreamEvent(type=AgentEventType.TOKEN, token="第一轮"),
    ]

    first = await context.client.post(
        "/invocations",
        json=_payload(conversation, message="读取收件箱"),
        headers=_headers("user-1"),
    )
    assert first.status_code == 200
    assert [frame[0] for frame in _parse_sse_frames(first.text)] == [
        "auth_card",
        None,
        None,
        None,
    ]

    context.handler.stream_events = [
        AgentStreamEvent(type=AgentEventType.TOKEN, token="第二轮"),
    ]
    second = await context.client.post(
        "/invocations",
        json=_payload(conversation, message="继续"),
        headers=_headers("user-1"),
    )

    assert second.status_code == 200
    second_frames = _parse_sse_frames(second.text)
    assert second_frames == [
        (None, {"token": "第二轮", "done": False}),
        (None, {"token": "", "done": True}),
    ]
    assert AUTH_URL not in second.text
    assert CUSTOM_EVENT_DATA["status"] not in second.text

    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [
        message.content.parts[0].text
        for message in messages
        if message.role == "assistant"
    ] == ["第一轮", "第二轮"]
    assert AUTH_URL not in json.dumps(
        [message.content.model_dump() for message in messages],
        ensure_ascii=False,
    )
