from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from alembic import command
from alembic.config import Config

from app.conversations.locks import ConversationBusyError, ConversationLock
from app.conversations.models import (
    DEFAULT_CONVERSATION_TITLE,
    MessageContent,
    TextMessagePart,
)
from app.conversations.service import ConversationNotFoundError, ConversationService
from app.conversations.store import ConversationStore
from app.database import Database
from app.main import app
from tests.conftest import PostgresTestSchema

SERVICE_ROOT = Path(__file__).resolve().parents[2]


class FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted_threads: list[str] = []
        self.fail = False

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)
        if self.fail:
            raise RuntimeError("checkpoint unavailable")


def _token(subject: str) -> str:
    def encode(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject})}.gateway-signature"


def _headers(subject: str, *, forged_user_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_token(subject)}"}
    if forged_user_id is not None:
        headers["X-HW-AgentGateway-User-Id"] = forged_user_id
    return headers


@pytest.fixture
def fake_checkpointer() -> FakeCheckpointer:
    return FakeCheckpointer()


@pytest.fixture
async def conversation_database(
    postgres_schema: PostgresTestSchema,
    fake_checkpointer: FakeCheckpointer,
) -> AsyncIterator[Database]:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")

    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
    )
    await database.startup()
    previous_database = getattr(app.state, "database", None)
    previous_handler = getattr(app.state, "agent_handler", None)
    app.state.database = database
    app.state.agent_handler = SimpleNamespace(checkpointer=fake_checkpointer)
    try:
        yield database
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


@pytest.fixture
async def conversation_client(
    conversation_database: Database,
) -> AsyncIterator[httpx.AsyncClient]:
    del conversation_database
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_conversation_api_crud_ownership_and_pagination(
    conversation_client: httpx.AsyncClient,
):
    created = await conversation_client.post(
        "/api/conversations",
        json={},
        headers=_headers("user-1", forged_user_id="attacker"),
    )
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == DEFAULT_CONVERSATION_TITLE
    assert conversation["status"] == "active"
    assert "user_id" not in conversation
    assert "pk" not in conversation

    conversation_id = conversation["id"]
    fetched = await conversation_client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1", forged_user_id="user-2"),
    )
    assert fetched.status_code == 200

    cross_user = await conversation_client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-2"),
    )
    assert cross_user.status_code == 404

    archived = await conversation_client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "  Project notes  ", "status": "archived"},
        headers=_headers("user-1"),
    )
    assert archived.status_code == 200
    assert archived.json()["title"] == "Project notes"
    assert archived.json()["archived_at"] is not None

    null_status = await conversation_client.patch(
        f"/api/conversations/{conversation_id}",
        json={"status": None},
        headers=_headers("user-1"),
    )
    assert null_status.status_code == 422

    active_list = await conversation_client.get(
        "/api/conversations",
        headers=_headers("user-1"),
    )
    assert active_list.json()["items"] == []

    archived_list = await conversation_client.get(
        "/api/conversations?status=archived",
        headers=_headers("user-1"),
    )
    assert [item["id"] for item in archived_list.json()["items"]] == [conversation_id]

    restored = await conversation_client.patch(
        f"/api/conversations/{conversation_id}",
        json={"status": "active"},
        headers=_headers("user-1"),
    )
    assert restored.json()["archived_at"] is None

    expected_ids = {conversation_id}
    for title in ("Second", "Third"):
        response = await conversation_client.post(
            "/api/conversations",
            json={"title": title},
            headers=_headers("user-1"),
        )
        assert response.status_code == 201
        expected_ids.add(response.json()["id"])

    first_page = await conversation_client.get(
        "/api/conversations?limit=2",
        headers=_headers("user-1"),
    )
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["next_cursor"]

    second_page = await conversation_client.get(
        "/api/conversations",
        params={"limit": 2, "cursor": first_payload["next_cursor"]},
        headers=_headers("user-1"),
    )
    second_payload = second_page.json()
    assert len(second_payload["items"]) == 1
    assert second_payload["next_cursor"] is None
    assert {
        item["id"] for item in first_payload["items"] + second_payload["items"]
    } == expected_ids


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_message_store_uniqueness_history_ownership_and_cascade(
    conversation_database: Database,
):
    store = ConversationStore(conversation_database)
    service = ConversationService(store)
    conversation = await store.create(user_id="user-1", title="Messages")
    content = MessageContent(parts=[TextMessagePart(text="Hello")])

    user_message = await store.insert_user_message(
        conversation_pk=conversation.pk,
        client_message_id=conversation.id,
        content=content,
    )
    assert user_message is not None
    duplicate = await store.insert_user_message(
        conversation_pk=conversation.pk,
        client_message_id=conversation.id,
        content=content,
    )
    assert duplicate is None

    assistant_message = await store.insert_assistant_message(
        conversation_pk=conversation.pk,
        reply_to_message_id=user_message.id,
        content=MessageContent(parts=[TextMessagePart(text="Hi")]),
    )
    history = await service.list_messages(
        user_id="user-1",
        conversation_id=conversation.id,
        cursor=None,
        limit=1,
    )
    assert [item.role for item in history.items] == ["user"]
    assert history.next_cursor == str(user_message.sequence)

    next_page = await service.list_messages(
        user_id="user-1",
        conversation_id=conversation.id,
        cursor=history.next_cursor,
        limit=10,
    )
    assert [item.id for item in next_page.items] == [assistant_message.id]

    with pytest.raises(ConversationNotFoundError):
        await service.list_messages(
            user_id="user-2",
            conversation_id=conversation.id,
            cursor=None,
            limit=10,
        )

    async with conversation_database.connection() as connection:
        await connection.execute(
            "DELETE FROM conversations WHERE pk = %s",
            (conversation.pk,),
        )
    async with conversation_database.connection() as connection:
        result = await connection.execute(
            "SELECT count(*) AS count FROM conversation_messages "
            "WHERE conversation_pk = %s",
            (conversation.pk,),
        )
        row = await result.fetchone()
    assert row["count"] == 0


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_conversation_api_rejects_invalid_identity_and_cursor(
    conversation_client: httpx.AsyncClient,
):
    missing_identity = await conversation_client.get("/api/conversations")
    assert missing_identity.status_code == 401

    malformed_identity = await conversation_client.get(
        "/api/conversations",
        headers={"Authorization": "Bearer malformed"},
    )
    assert malformed_identity.status_code == 401

    invalid_cursor = await conversation_client.get(
        "/api/conversations?cursor=not-a-cursor",
        headers=_headers("user-1"),
    )
    assert invalid_cursor.status_code == 400


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_advisory_lock_conflict_parallelism_and_exception_release(
    conversation_database: Database,
):
    store = ConversationStore(conversation_database)
    first = await store.create(user_id="user-1", title="First")
    second = await store.create(user_id="user-1", title="Second")
    lock = ConversationLock(conversation_database)

    async with lock.acquire(first.pk):
        with pytest.raises(ConversationBusyError):
            async with lock.acquire(first.pk):
                pytest.fail("the same conversation lock must not be re-entered")
        async with lock.acquire(second.pk):
            pass

    with pytest.raises(RuntimeError, match="business failure"):
        async with lock.acquire(first.pk):
            raise RuntimeError("business failure")

    async with lock.acquire(first.pk):
        pass


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_lock_pool_saturation_does_not_block_store_connections(
    postgres_schema: PostgresTestSchema,
):
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = postgres_schema.dsn
    config.attributes["schema"] = postgres_schema.name
    command.upgrade(config, "head")
    database = Database(
        postgres_schema.dsn,
        connection_kwargs={"options": f"-csearch_path={postgres_schema.name}"},
        max_size=2,
        lock_max_size=2,
    )
    await database.startup()
    try:
        store = ConversationStore(database)
        conversations = [
            await store.create(user_id="user-1", title=title)
            for title in ("First", "Second")
        ]
        lock = ConversationLock(database)

        async def read_while_locked(record):
            async with lock.acquire(record.pk):
                return await store.get(
                    user_id=record.user_id,
                    conversation_id=record.id,
                )

        results = await asyncio.wait_for(
            asyncio.gather(*(read_while_locked(item) for item in conversations)),
            timeout=2,
        )
        assert [result.id for result in results if result] == [
            item.id for item in conversations
        ]
    finally:
        await database.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_delete_is_locked_idempotent_and_user_scoped(
    conversation_client: httpx.AsyncClient,
    conversation_database: Database,
    fake_checkpointer: FakeCheckpointer,
):
    created = await conversation_client.post(
        "/api/conversations",
        json={"title": "Delete me"},
        headers=_headers("user-1"),
    )
    conversation_id = created.json()["id"]
    record = await ConversationStore(conversation_database).get(
        user_id="user-1",
        conversation_id=conversation_id,
    )
    assert record is not None

    lock = ConversationLock(conversation_database)
    async with lock.acquire(record.pk):
        busy = await conversation_client.delete(
            f"/api/conversations/{conversation_id}",
            headers=_headers("user-1"),
        )
    assert busy.status_code == 409
    assert busy.json() == {
        "code": "conversation_busy",
        "detail": "conversation is busy",
    }

    other_user = await conversation_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-2"),
    )
    assert other_user.status_code == 204
    still_present = await conversation_client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert still_present.status_code == 200

    deleted = await conversation_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert deleted.status_code == 204
    repeated = await conversation_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert repeated.status_code == 204
    assert fake_checkpointer.deleted_threads == [
        f"user-2:{conversation_id}",
        f"user-1:{conversation_id}",
        f"user-1:{conversation_id}",
    ]


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_delete_reports_checkpoint_failure_after_business_delete(
    conversation_client: httpx.AsyncClient,
    fake_checkpointer: FakeCheckpointer,
):
    created = await conversation_client.post(
        "/api/conversations",
        json={},
        headers=_headers("user-1"),
    )
    conversation_id = created.json()["id"]
    fake_checkpointer.fail = True

    failed = await conversation_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert failed.status_code == 502
    missing = await conversation_client.get(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert missing.status_code == 404

    fake_checkpointer.fail = False
    retried = await conversation_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=_headers("user-1"),
    )
    assert retried.status_code == 204
