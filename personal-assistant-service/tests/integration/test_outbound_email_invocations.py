"""Outbound Email behavior at the Feature 14 invocation boundary."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
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
EMAIL_USER_ID = "email-user"

pytestmark = pytest.mark.integration


class FakeEmailHandler:
    """Return canned email responses with Guard state scoped by Conversation."""

    INBOX_RESPONSE = (
        "你有 3 封未读邮件：\n\n"
        "| 发件人 | 主题 | 时间 |\n"
        "|------|------|------|\n"
        "| 张三 | 项目进度更新 | 2026-06-14 |\n"
        "| 李四 | 会议邀请：Q2 复盘 | 2026-06-13 |\n"
        "| 王五 | 报销审批通知 | 2026-06-12 |"
    )
    SEARCH_RESPONSE = (
        "搜索到 2 封关于「项目进度」的邮件：\n\n"
        "| 发件人 | 主题 | 时间 |\n"
        "|------|------|------|\n"
        "| 张三 | 项目进度更新 | 2026-06-14 |\n"
        "| 赵六 | 项目进度阻塞风险 | 2026-06-10 |\n\n"
        "需要查看哪封邮件的详细内容？"
    )
    REPLY_PREVIEW = (
        "📧 **回复预览**\n\n"
        "**收件人**: 张三 <zhangsan@example.com>\n"
        "**主题**: Re: 项目进度更新\n"
        "**正文**:\n"
        "> 收到，感谢更新。我会根据最新进度调整计划。\n\n"
        "---\n"
        "是否确认发送此回复？（回复「发送」确认，回复「取消」放弃）"
    )
    REPLY_SENT = "邮件已回复 ✅"
    REPLY_CANCELLED = "已取消，不发送。"
    SEND_PREVIEW = (
        "📧 **新邮件预览**\n\n"
        "**收件人**: zhangsan@example.com\n"
        "**主题**: 你好\n"
        "**正文**:\n"
        "> 你好\n\n"
        "---\n"
        "需要发送吗？请回复「确认」发送，或「取消」放弃。"
    )
    GENERIC = "我是你的 Personal Assistant，可以帮你处理邮件、日程等事务。"

    def __init__(self) -> None:
        self.handle_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str]] = []
        self._conversation_state: dict[str, str] = {}

    async def handle(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> str:
        self.handle_calls.append((message, user_id, conversation_id))
        return self._respond(message, conversation_id)

    async def handle_stream(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        self.stream_calls.append((message, user_id, conversation_id))
        response = self._respond(message, conversation_id)
        yield AgentStreamEvent(
            type=AgentEventType.CUSTOM,
            data={"type": "email_progress", "status": "complete"},
        )
        midpoint = len(response) // 2
        for token in (response[:midpoint], response[midpoint:]):
            yield AgentStreamEvent(type=AgentEventType.TOKEN, token=token)

    def _respond(self, message: str, conversation_id: str) -> str:
        state = self._conversation_state.get(conversation_id)
        if state == "awaiting_reply":
            state = _resolve_guard(
                message,
                state,
                confirm_value="reply_sent",
                cancel_value="reply_cancelled",
            )
            self._conversation_state[conversation_id] = state
            return _guard_response(
                state,
                sent=self.REPLY_SENT,
                cancelled=self.REPLY_CANCELLED,
                preview=self.REPLY_PREVIEW,
            )
        if state == "awaiting_send":
            state = _resolve_guard(
                message,
                state,
                confirm_value="send_confirmed",
                cancel_value="send_cancelled",
            )
            self._conversation_state[conversation_id] = state
            return _guard_response(
                state,
                sent="邮件已发送 ✅",
                cancelled="已取消，不发送。",
                preview=self.SEND_PREVIEW,
            )
        if "收件箱" in message:
            return self.INBOX_RESPONSE
        if "搜索" in message or "查" in message:
            return self.SEARCH_RESPONSE
        if "回" in message and ("张三" in message or "邮件" in message):
            self._conversation_state[conversation_id] = "awaiting_reply"
            return self.REPLY_PREVIEW
        if "发邮件" in message or "发一封" in message:
            self._conversation_state[conversation_id] = "awaiting_send"
            return self.SEND_PREVIEW
        return self.GENERIC


_CONFIRM_TERMS = {"发送", "确认", "好的", "确认发送", "好的，发送", "是"}
_CANCEL_TERMS = {"取消", "不发送", "先不发了", "不要发", "否"}


def _resolve_guard(
    message: str,
    current_state: str,
    *,
    confirm_value: str,
    cancel_value: str,
) -> str:
    intent = message.strip().lower()
    if intent in _CONFIRM_TERMS:
        return confirm_value
    if intent in _CANCEL_TERMS:
        return cancel_value
    return current_state


def _guard_response(state: str, *, sent: str, cancelled: str, preview: str) -> str:
    if "sent" in state or "confirmed" in state:
        return sent
    if "cancelled" in state:
        return cancelled
    return preview


@dataclass
class EmailInvocationContext:
    client: httpx.AsyncClient
    handler: FakeEmailHandler
    store: ConversationStore


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.signature"


def _headers(*, stream: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_token(EMAIL_USER_ID)}",
        ACCESS_TOKEN_HEADER: "gateway-workload-token",
        SESSION_HEADER: "shared-runtime-session",
    }
    if stream:
        headers["Accept"] = "text/event-stream"
    return headers


def _payload(
    conversation: ConversationRecord,
    *,
    message: str,
    stream: bool = False,
    client_message_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "conversation_id": str(conversation.id),
        "client_message_id": str(client_message_id or uuid4()),
        "message": message,
        "stream": stream,
    }


async def _post(
    context: EmailInvocationContext,
    conversation: ConversationRecord,
    message: str,
    *,
    stream: bool = False,
) -> httpx.Response:
    return await context.client.post(
        "/invocations",
        json=_payload(conversation, message=message, stream=stream),
        headers=_headers(stream=stream),
    )


def _sse_payloads(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
async def email_invocation_context(
    postgres_schema: PostgresTestSchema,
) -> AsyncIterator[EmailInvocationContext]:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")

    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
    )
    await database.startup()
    handler = FakeEmailHandler()
    previous_database = getattr(app.state, "database", None)
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.database = database
    app.state.agent_handler = handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield EmailInvocationContext(
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


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_email_listing_and_search_use_conversation_contract(
    email_invocation_context: EmailInvocationContext,
) -> None:
    context = email_invocation_context
    conversation = await context.store.create(user_id=EMAIL_USER_ID, title="Email")

    inbox = await _post(context, conversation, "帮我看看收件箱")
    search = await _post(
        context,
        conversation,
        "帮我查一下最近关于项目进度的邮件",
        stream=True,
    )

    assert inbox.status_code == 200
    assert inbox.json() == {"response": FakeEmailHandler.INBOX_RESPONSE}
    assert search.status_code == 200
    search_payloads = _sse_payloads(search)
    assert search_payloads[0] == {"type": "email_progress", "status": "complete"}
    assert (
        "".join(
            str(payload["token"]) for payload in search_payloads if payload.get("token")
        )
        == FakeEmailHandler.SEARCH_RESPONSE
    )
    assert context.handler.handle_calls == [
        ("帮我看看收件箱", EMAIL_USER_ID, str(conversation.id))
    ]
    assert context.handler.stream_calls == [
        ("帮我查一下最近关于项目进度的邮件", EMAIL_USER_ID, str(conversation.id))
    ]

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
    ] == [FakeEmailHandler.INBOX_RESPONSE, FakeEmailHandler.SEARCH_RESPONSE]


@pytest.mark.parametrize(
    ("decision", "expected", "forbidden"),
    [
        ("发送", "已回复", "已取消"),
        ("取消", "已取消", "已回复"),
    ],
)
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_reply_guard_requires_preview_before_decision(
    email_invocation_context: EmailInvocationContext,
    decision: str,
    expected: str,
    forbidden: str,
) -> None:
    context = email_invocation_context
    conversation = await context.store.create(user_id=EMAIL_USER_ID, title="Reply")

    preview = await _post(context, conversation, "帮我回张三的邮件，说收到")
    result = await _post(context, conversation, decision)

    assert preview.status_code == 200
    assert preview.json() == {"response": FakeEmailHandler.REPLY_PREVIEW}
    assert "已回复" not in preview.json()["response"]
    assert "已发送" not in preview.json()["response"]
    assert result.status_code == 200
    assert expected in result.json()["response"]
    assert forbidden not in result.json()["response"]
    assert context.handler.handle_calls == [
        ("帮我回张三的邮件，说收到", EMAIL_USER_ID, str(conversation.id)),
        (decision, EMAIL_USER_ID, str(conversation.id)),
    ]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_direct_send_stops_at_confirmation_preview(
    email_invocation_context: EmailInvocationContext,
) -> None:
    context = email_invocation_context
    conversation = await context.store.create(user_id=EMAIL_USER_ID, title="Send")

    response = await _post(
        context,
        conversation,
        "帮zhangsan@example.com发邮件说你好",
    )

    assert response.status_code == 200
    assert response.json() == {"response": FakeEmailHandler.SEND_PREVIEW}
    assert "已发送" not in response.json()["response"]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_guard_state_is_independent_across_conversations(
    email_invocation_context: EmailInvocationContext,
) -> None:
    context = email_invocation_context
    conversation_a = await context.store.create(
        user_id=EMAIL_USER_ID,
        title="Reply",
    )
    conversation_b = await context.store.create(
        user_id=EMAIL_USER_ID,
        title="Inbox",
    )

    preview_a = await _post(context, conversation_a, "帮我回张三的邮件，说收到")
    inbox_b = await _post(context, conversation_b, "帮我看看收件箱")
    cancelled_a = await _post(context, conversation_a, "取消")

    assert preview_a.json() == {"response": FakeEmailHandler.REPLY_PREVIEW}
    assert inbox_b.json() == {"response": FakeEmailHandler.INBOX_RESPONSE}
    assert "请先授权" not in inbox_b.json()["response"]
    assert "需要登录 Microsoft 365" not in inbox_b.json()["response"]
    assert cancelled_a.json() == {"response": FakeEmailHandler.REPLY_CANCELLED}
    assert context.handler.handle_calls == [
        ("帮我回张三的邮件，说收到", EMAIL_USER_ID, str(conversation_a.id)),
        ("帮我看看收件箱", EMAIL_USER_ID, str(conversation_b.id)),
        ("取消", EMAIL_USER_ID, str(conversation_a.id)),
    ]

    messages_a = await context.store.list_messages(
        conversation_pk=conversation_a.pk,
        after_sequence=None,
        limit=10,
    )
    messages_b = await context.store.list_messages(
        conversation_pk=conversation_b.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages_a] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [message.role for message in messages_b] == ["user", "assistant"]
    assert messages_b[-1].content.parts[0].text == FakeEmailHandler.INBOX_RESPONSE


def _make_passthrough_decorator(*args, **kwargs):
    """Return the decorated function without injecting an access token."""

    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(*fargs, **fkwargs):
            return await func(*fargs, **fkwargs)

        return wrapper

    return decorator


def _import_email_tools():
    """Import email_tools with the AgentArts decorator boundary mocked."""
    mock_agentarts_sdk = MagicMock()
    mock_agentarts_sdk.require_access_token = _make_passthrough_decorator
    mock_agentarts_sdk.IdentityClient = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "agentarts": MagicMock(),
            "agentarts.sdk": mock_agentarts_sdk,
            "agentarts.sdk.identity": MagicMock(),
            "agentarts.sdk.identity.types": MagicMock(),
        },
    ):
        from app.tools import email_tools

        return email_tools


def _mock_graph_client():
    """Return an async Graph client whose requests receive HTTP 202."""
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.request = AsyncMock(return_value=mock_response)
    return mock_client


def test_email_public_tool_signatures_exclude_access_token() -> None:
    email_tools = _import_email_tools()

    assert list(inspect.signature(email_tools.send_email).parameters) == [
        "to",
        "subject",
        "body",
        "cc",
    ]
    assert list(inspect.signature(email_tools.reply_to_email).parameters) == [
        "email_id",
        "body",
    ]


def test_send_email_calls_m365_request_boundary() -> None:
    email_tools = _import_email_tools()
    mock_client = _mock_graph_client()

    with patch.object(
        email_tools,
        "_m365_email_request",
        AsyncMock(return_value=mock_client.request.return_value),
    ) as request:
        result = asyncio.run(
            email_tools.send_email(
                to=["test@example.com"],
                subject="Hello",
                body="This is a test email",
            )
        )

    assert result["sent"] is True
    assert result["error"] is None
    request.assert_awaited_once()
    assert request.call_args.args[:2] == ("POST", "/sendMail")


def test_send_email_input_validation() -> None:
    email_tools = _import_email_tools()

    with patch.object(email_tools, "_m365_email_request", AsyncMock()) as request:
        result = asyncio.run(
            email_tools.send_email(
                to=[],
                subject="Test",
                body="Body",
            )
        )

    assert result["sent"] is False
    assert "recipient" in result["error"].lower()
    request.assert_not_awaited()


def test_reply_to_email_input_validation() -> None:
    email_tools = _import_email_tools()

    with patch.object(email_tools, "_m365_email_request", AsyncMock()) as request:
        empty_id = asyncio.run(
            email_tools.reply_to_email(email_id="", body="Some reply")
        )
        empty_body = asyncio.run(email_tools.reply_to_email(email_id="msg123", body=""))
        whitespace_body = asyncio.run(
            email_tools.reply_to_email(email_id="msg123", body="   ")
        )

    assert empty_id["sent"] is False
    assert "email_id" in empty_id["error"].lower()
    assert empty_body["sent"] is False
    assert "body" in empty_body["error"].lower()
    assert whitespace_body["sent"] is False
    assert "body" in whitespace_body["error"].lower()
    request.assert_not_awaited()
