"""Web Chat behavior at the Feature 14 invocation boundary."""

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
WEB_CHAT_USER_ID = "web-chat-user"

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class FakeWebChatAgentHandler:
    """Emit structured Agent events while echoing Web Chat input."""

    def __init__(self) -> None:
        self.stream_calls: list[tuple[str, str, str]] = []

    async def handle_stream(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        self.stream_calls.append((message, user_id, conversation_id))
        yield AgentStreamEvent(
            type=AgentEventType.CUSTOM,
            data={"status": "working"},
        )
        yield AgentStreamEvent(type=AgentEventType.TOKEN, token="Assistant: ")
        yield AgentStreamEvent(type=AgentEventType.TOKEN, token=message)


@dataclass
class WebChatTestContext:
    client: httpx.AsyncClient
    handler: FakeWebChatAgentHandler
    store: ConversationStore


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.signature"


def _headers(subject: str = WEB_CHAT_USER_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject)}",
        ACCESS_TOKEN_HEADER: "gateway-workload-token",
        SESSION_HEADER: "web-chat-runtime-session",
    }


@pytest.fixture
async def web_chat_context(
    postgres_schema: PostgresTestSchema,
) -> AsyncIterator[WebChatTestContext]:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")

    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
    )
    await database.startup()
    handler = FakeWebChatAgentHandler()
    previous_database = getattr(app.state, "database", None)
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.database = database
    app.state.agent_handler = handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield WebChatTestContext(
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


async def _post_stream(
    context: WebChatTestContext,
    conversation: ConversationRecord,
    message: str,
    *,
    client_message_id: UUID,
) -> httpx.Response:
    return await context.client.post(
        "/invocations",
        json={
            "conversation_id": str(conversation.id),
            "client_message_id": str(client_message_id),
            "message": message,
            "stream": True,
        },
        headers={**_headers(), "Accept": "text/event-stream"},
    )


def _sse_payloads(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_web_chat_preserves_unicode_and_structured_agent_events(
    web_chat_context: WebChatTestContext,
):
    context = web_chat_context
    conversation = await context.store.create(
        user_id=WEB_CHAT_USER_ID,
        title="Unicode",
    )
    client_message_id = uuid4()
    message = "你好，Web Chat！\nSpecial: +@#$% & = ?"

    response = await _post_stream(
        context,
        conversation,
        message,
        client_message_id=client_message_id,
    )

    assert response.status_code == 200
    assert _sse_payloads(response) == [
        {"status": "working"},
        {"token": "Assistant: ", "done": False},
        {"token": message, "done": False},
        {"token": "", "done": True},
    ]
    assert context.handler.stream_calls == [
        (message, WEB_CHAT_USER_ID, str(conversation.id))
    ]

    owned_conversation = await context.store.get(
        user_id=WEB_CHAT_USER_ID,
        conversation_id=conversation.id,
    )
    assert owned_conversation is not None
    assert owned_conversation.user_id == WEB_CHAT_USER_ID
    persisted = await context.store.list_messages(
        conversation_pk=owned_conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [item.role for item in persisted] == ["user", "assistant"]
    assert persisted[0].client_message_id == client_message_id
    assert persisted[0].content.parts[0].text == message
    assert persisted[1].content.parts[0].text == f"Assistant: {message}"
    assert persisted[1].reply_to_message_id == persisted[0].id


@pytest.mark.asyncio
async def test_web_chat_multi_turn_messages_persist_in_order(
    web_chat_context: WebChatTestContext,
):
    context = web_chat_context
    conversation = await context.store.create(
        user_id=WEB_CHAT_USER_ID,
        title="Multi-turn",
    )
    messages = ["Hello", "How are you?", "What time is it?"]
    client_message_ids = [uuid4() for _ in messages]

    for message, client_message_id in zip(messages, client_message_ids, strict=True):
        response = await _post_stream(
            context,
            conversation,
            message,
            client_message_id=client_message_id,
        )
        assert response.status_code == 200
        assert _sse_payloads(response)[-1] == {"token": "", "done": True}

    assert context.handler.stream_calls == [
        (message, WEB_CHAT_USER_ID, str(conversation.id)) for message in messages
    ]
    persisted = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [item.role for item in persisted] == ["user", "assistant"] * len(messages)
    for index, (message, client_message_id) in enumerate(
        zip(messages, client_message_ids, strict=True)
    ):
        user_message = persisted[index * 2]
        assistant_message = persisted[index * 2 + 1]
        assert user_message.client_message_id == client_message_id
        assert user_message.content.parts[0].text == message
        assert assistant_message.content.parts[0].text == f"Assistant: {message}"
        assert assistant_message.reply_to_message_id == user_message.id
