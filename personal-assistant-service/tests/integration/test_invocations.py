from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from agentarts.sdk.runtime.model import (
    ACCESS_TOKEN_HEADER,
    SESSION_HEADER,
    USER_ID_HEADER,
)
from alembic import command
from alembic.config import Config

from app.conversations.models import ConversationStatus
from app.conversations.store import ConversationRecord, ConversationStore
from app.database import Database
from app.invocations.models import (
    AgentEventType,
    AgentStreamEvent,
    InvocationRequest,
)
from app.invocations.service import InvocationService
from app.main import app
from tests.conftest import PostgresTestSchema

SERVICE_ROOT = Path(__file__).resolve().parents[2]


class FakeAgentHandler:
    def __init__(self) -> None:
        self.response = "Hello from the assistant"
        self.stream_events = [
            AgentStreamEvent(type=AgentEventType.TOKEN, token="Hello"),
            AgentStreamEvent(type=AgentEventType.TOKEN, token=" world"),
        ]
        self.sync_error: Exception | None = None
        self.stream_error: Exception | None = None
        self.on_handle: Callable[[], Awaitable[None]] | None = None
        self.handle_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str, str]] = []
        self.checkpointer = self

    async def handle(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> str:
        self.handle_calls.append((message, user_id, conversation_id))
        if self.on_handle:
            await self.on_handle()
        if self.sync_error:
            raise self.sync_error
        return self.response

    async def handle_stream(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        self.stream_calls.append((message, user_id, conversation_id))
        if self.stream_error:
            raise self.stream_error
        for event in self.stream_events:
            yield event

    async def adelete_thread(self, thread_id: str) -> None:
        del thread_id


@dataclass
class InvocationTestContext:
    client: httpx.AsyncClient
    database: Database
    handler: FakeAgentHandler
    store: ConversationStore


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.gateway-signature"


def _headers(subject: str, *, forged_user_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_token(subject)}",
        ACCESS_TOKEN_HEADER: "gateway-workload-token",
        SESSION_HEADER: "runtime-cookie-session",
    }
    if forged_user_id is not None:
        headers[USER_ID_HEADER] = forged_user_id
    return headers


def _payload(
    conversation: ConversationRecord,
    *,
    client_message_id: UUID | None = None,
    stream: bool = False,
) -> dict[str, object]:
    return {
        "conversation_id": str(conversation.id),
        "client_message_id": str(client_message_id or uuid4()),
        "message": "Hello",
        "stream": stream,
    }


def _sse_payloads(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.fixture
async def invocation_context(
    postgres_schema: PostgresTestSchema,
) -> AsyncIterator[InvocationTestContext]:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")

    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
    )
    await database.startup()
    handler = FakeAgentHandler()
    previous_database = getattr(app.state, "database", None)
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.database = database
    app.state.agent_handler = handler

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield InvocationTestContext(
                client=client,
                database=database,
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
async def test_sync_persists_user_before_agent_and_assistant_before_response(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Sync")

    async def assert_user_is_durable() -> None:
        messages = await context.store.list_messages(
            conversation_pk=conversation.pk,
            after_sequence=None,
            limit=10,
        )
        assert [message.role for message in messages] == ["user"]

    context.handler.on_handle = assert_user_is_durable
    response = await context.client.post(
        "/invocations",
        json=_payload(conversation),
        headers=_headers("user-1", forged_user_id="attacker"),
    )

    assert response.status_code == 200
    assert response.json() == {"response": context.handler.response}
    assert context.handler.handle_calls == [("Hello", "user-1", str(conversation.id))]
    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].reply_to_message_id == messages[0].id
    assert messages[1].content.parts[0].text == context.handler.response


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stream_commits_assistant_before_success_terminal(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Stream")
    request = InvocationRequest.model_validate(_payload(conversation, stream=True))
    execution = await InvocationService(context.database).prepare(
        request=request,
        user_id="user-1",
        handler=context.handler,
    )
    stream = execution.stream_sse()

    first = json.loads((await anext(stream)).removeprefix("data: "))
    assert first == {"token": "Hello", "done": False}
    before_done = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in before_done] == ["user"]

    second = json.loads((await anext(stream)).removeprefix("data: "))
    assert second == {"token": " world", "done": False}
    terminal = json.loads((await anext(stream)).removeprefix("data: "))
    assert terminal == {"token": "", "done": True}
    after_done = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in after_done] == ["user", "assistant"]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_cancelled_stream_releases_conversation_lock(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Cancelled")
    execution = await InvocationService(context.database).prepare(
        request=InvocationRequest.model_validate(_payload(conversation, stream=True)),
        user_id="user-1",
        handler=context.handler,
    )
    stream = execution.stream_sse()

    first = json.loads((await anext(stream)).removeprefix("data: "))
    assert first == {"token": "Hello", "done": False}
    await stream.aclose()

    next_execution = await InvocationService(context.database).prepare(
        request=InvocationRequest.model_validate(_payload(conversation, stream=True)),
        user_id="user-1",
        handler=context.handler,
    )
    await next_execution.close()

    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == ["user", "user"]


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_cancel_command_stops_stream_before_next_invocation(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Cancel API")

    class BlockingAgentHandler(FakeAgentHandler):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def handle_stream(
            self,
            message: str,
            user_id: str,
            conversation_id: str,
        ) -> AsyncIterator[AgentStreamEvent]:
            del message, user_id, conversation_id
            self.started.set()
            yield AgentStreamEvent(type=AgentEventType.TOKEN, token="partial")
            await self.release.wait()

    blocking_handler = BlockingAgentHandler()
    app.state.agent_handler = blocking_handler
    client_message_id = uuid4()
    first_request = asyncio.create_task(
        context.client.post(
            "/invocations",
            json=_payload(
                conversation,
                client_message_id=client_message_id,
                stream=True,
            ),
            headers=_headers("user-1"),
        )
    )
    await blocking_handler.started.wait()

    cancelled = await context.client.post(
        f"/api/conversations/{conversation.id}/invocations/{client_message_id}/cancel",
        headers=_headers("user-1"),
    )
    assert cancelled.status_code == 204
    first_result = await asyncio.gather(first_request, return_exceptions=True)
    assert isinstance(first_result[0], (httpx.Response, AssertionError))

    app.state.agent_handler = context.handler
    retried = await context.client.post(
        "/invocations",
        json=_payload(conversation),
        headers=_headers("user-1"),
    )
    assert retried.status_code == 200

    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == ["user", "user", "assistant"]


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_cancel_command_arriving_first_prevents_late_invocation(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Early cancel")
    client_message_id = uuid4()

    cancelled = await context.client.post(
        f"/api/conversations/{conversation.id}/invocations/{client_message_id}/cancel",
        headers=_headers("user-1"),
    )
    assert cancelled.status_code == 204

    late_invocation = await context.client.post(
        "/invocations",
        json=_payload(conversation, client_message_id=client_message_id),
        headers=_headers("user-1"),
    )
    assert late_invocation.status_code == 409
    assert late_invocation.json() == {
        "code": "invocation_cancelled",
        "detail": "invocation was cancelled before execution began",
    }
    assert context.handler.handle_calls == []

    continued = await context.client.post(
        "/invocations",
        json=_payload(conversation),
        headers=_headers("user-1"),
    )
    assert continued.status_code == 200


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_duplicate_message_and_busy_conversation_return_pre_stream_409(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Conflicts")
    client_message_id = uuid4()
    payload = _payload(conversation, client_message_id=client_message_id)

    first = await context.client.post(
        "/invocations",
        json=payload,
        headers=_headers("user-1"),
    )
    duplicate = await context.client.post(
        "/invocations",
        json=payload,
        headers=_headers("user-1"),
    )
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "code": "duplicate_message",
        "detail": "client_message_id already exists",
    }
    assert len(context.handler.handle_calls) == 1

    prepared = await InvocationService(context.database).prepare(
        request=InvocationRequest.model_validate(
            _payload(conversation, client_message_id=uuid4())
        ),
        user_id="user-1",
        handler=context.handler,
    )
    try:
        busy = await context.client.post(
            "/invocations",
            json=_payload(conversation, client_message_id=uuid4(), stream=True),
            headers=_headers("user-1"),
        )
    finally:
        await prepared.close()
    assert busy.status_code == 409
    assert busy.headers["content-type"].startswith("application/json")
    assert busy.json() == {
        "code": "conversation_busy",
        "detail": "conversation is busy",
    }


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_archived_and_cross_user_conversations_are_rejected(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Archived")
    await context.store.update(
        user_id="user-1",
        conversation_id=conversation.id,
        title=None,
        status=ConversationStatus.ARCHIVED,
    )

    archived = await context.client.post(
        "/invocations",
        json=_payload(conversation),
        headers=_headers("user-1"),
    )
    cross_user = await context.client.post(
        "/invocations",
        json=_payload(conversation),
        headers=_headers("user-2"),
    )
    assert archived.status_code == 409
    assert archived.json() == {
        "code": "conversation_archived",
        "detail": "conversation is archived",
    }
    assert cross_user.status_code == 404
    assert context.handler.handle_calls == []


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_agent_failures_keep_only_user_message(
    invocation_context: InvocationTestContext,
):
    context = invocation_context
    sync_conversation = await context.store.create(user_id="user-1", title="Failure")
    context.handler.sync_error = RuntimeError("agent failed")
    sync_response = await context.client.post(
        "/invocations",
        json=_payload(sync_conversation),
        headers=_headers("user-1"),
    )
    assert sync_response.status_code == 500
    sync_messages = await context.store.list_messages(
        conversation_pk=sync_conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in sync_messages] == ["user"]

    context.handler.sync_error = None
    context.handler.stream_error = RuntimeError("stream failed")
    stream_conversation = await context.store.create(user_id="user-1", title="Stream")
    stream_response = await context.client.post(
        "/invocations",
        json=_payload(stream_conversation, stream=True),
        headers=_headers("user-1"),
    )
    assert stream_response.status_code == 200
    assert _sse_payloads(stream_response) == [
        {
            "error": "The assistant could not complete this request.",
            "done": False,
        }
    ]
    stream_messages = await context.store.list_messages(
        conversation_pk=stream_conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in stream_messages] == ["user"]


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_assistant_commit_failure_never_emits_success_done(
    invocation_context: InvocationTestContext,
    monkeypatch: pytest.MonkeyPatch,
):
    context = invocation_context
    conversation = await context.store.create(user_id="user-1", title="Commit")
    execution = await InvocationService(context.database).prepare(
        request=InvocationRequest.model_validate(_payload(conversation, stream=True)),
        user_id="user-1",
        handler=context.handler,
    )

    async def fail_commit(**kwargs):
        del kwargs
        raise RuntimeError("assistant commit failed")

    monkeypatch.setattr(execution._store, "insert_assistant_message", fail_commit)
    events = [
        json.loads(event.removeprefix("data: "))
        async for event in execution.stream_sse()
    ]

    assert events[-1] == {
        "error": "The assistant could not complete this request.",
        "done": False,
    }
    assert {"token": "", "done": True} not in events
    messages = await context.store.list_messages(
        conversation_pk=conversation.pk,
        after_sequence=None,
        limit=10,
    )
    assert [message.role for message in messages] == ["user"]


def test_invocation_openapi_uses_required_snake_case_fields():
    operation = app.openapi()["paths"]["/invocations"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert set(schema["required"]) == {
        "conversation_id",
        "client_message_id",
        "message",
    }
    assert set(schema["properties"]) == {
        "conversation_id",
        "client_message_id",
        "message",
        "stream",
    }
    assert operation["responses"]["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiError"
    }
