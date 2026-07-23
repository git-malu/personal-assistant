from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.conversations.models import (
    ConversationStatus,
    MessageContent,
    MessageRole,
)
from app.database import Database


@dataclass(frozen=True)
class ConversationRecord:
    pk: int
    id: UUID
    user_id: str
    title: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class MessageRecord:
    sequence: int
    id: UUID
    conversation_pk: int
    reply_to_message_id: UUID | None
    role: MessageRole
    content: MessageContent
    client_message_id: UUID | None
    created_at: datetime


def _conversation(row: dict[str, Any]) -> ConversationRecord:
    return ConversationRecord(
        pk=row["pk"],
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        status=ConversationStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _message(row: dict[str, Any]) -> MessageRecord:
    return MessageRecord(
        sequence=row["sequence"],
        id=row["id"],
        conversation_pk=row["conversation_pk"],
        reply_to_message_id=row["reply_to_message_id"],
        role=MessageRole(row["role"]),
        content=MessageContent.model_validate(row["content"]),
        client_message_id=row["client_message_id"],
        created_at=row["created_at"],
    )


class ConversationStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        *,
        user_id: str,
        title: str,
        conversation_id: UUID | None = None,
    ) -> ConversationRecord:
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO conversations (id, user_id, title)
                VALUES (%s, %s, %s)
                RETURNING pk, id, user_id, title, status,
                          created_at, updated_at, archived_at
                """,
                (conversation_id or uuid4(), user_id, title),
            )
            row = await cursor.fetchone()
        return _conversation(row)

    async def get(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
    ) -> ConversationRecord | None:
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT pk, id, user_id, title, status,
                       created_at, updated_at, archived_at
                FROM conversations
                WHERE user_id = %s AND id = %s
                """,
                (user_id, conversation_id),
            )
            row = await cursor.fetchone()
        return _conversation(row) if row else None

    async def list(
        self,
        *,
        user_id: str,
        status: ConversationStatus,
        cursor: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[ConversationRecord]:
        parameters: list[object] = [user_id, status.value]
        cursor_filter = ""
        if cursor:
            cursor_filter = "AND (updated_at, id) < (%s, %s)"
            parameters.extend(cursor)
        parameters.append(limit)

        async with self._database.connection() as connection:
            result = await connection.execute(
                f"""
                SELECT pk, id, user_id, title, status,
                       created_at, updated_at, archived_at
                FROM conversations
                WHERE user_id = %s AND status = %s
                  {cursor_filter}
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                parameters,
            )
            rows = await result.fetchall()
        return [_conversation(row) for row in rows]

    async def update(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        title: str | None,
        status: ConversationStatus | None,
    ) -> ConversationRecord | None:
        status_value = status.value if status else None
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE conversations
                SET title = COALESCE(%s::text, title),
                    status = COALESCE(%s::text, status),
                    archived_at = CASE
                        WHEN %s::text = 'archived'
                            THEN COALESCE(archived_at, now())
                        WHEN %s::text = 'active' THEN NULL
                        ELSE archived_at
                    END,
                    updated_at = now()
                WHERE user_id = %s AND id = %s
                RETURNING pk, id, user_id, title, status,
                          created_at, updated_at, archived_at
                """,
                (
                    title,
                    status_value,
                    status_value,
                    status_value,
                    user_id,
                    conversation_id,
                ),
            )
            row = await cursor.fetchone()
        return _conversation(row) if row else None

    async def list_messages(
        self,
        *,
        conversation_pk: int,
        after_sequence: int | None,
        limit: int,
    ) -> list[MessageRecord]:
        parameters: list[object] = [conversation_pk]
        cursor_filter = ""
        if after_sequence is not None:
            cursor_filter = "AND sequence > %s"
            parameters.append(after_sequence)
        parameters.append(limit)

        async with self._database.connection() as connection:
            result = await connection.execute(
                f"""
                SELECT sequence, id, conversation_pk, reply_to_message_id,
                       role, content, client_message_id, created_at
                FROM conversation_messages
                WHERE conversation_pk = %s
                  {cursor_filter}
                ORDER BY sequence
                LIMIT %s
                """,
                parameters,
            )
            rows = await result.fetchall()
        return [_message(row) for row in rows]

    async def insert_user_message(
        self,
        *,
        conversation_pk: int,
        client_message_id: UUID,
        content: MessageContent,
    ) -> MessageRecord | None:
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO conversation_messages (
                    id, conversation_pk, role, content, client_message_id
                )
                VALUES (%s, %s, 'user', %s, %s)
                ON CONFLICT (conversation_pk, client_message_id)
                    WHERE role = 'user'
                    DO NOTHING
                RETURNING sequence, id, conversation_pk, reply_to_message_id,
                          role, content, client_message_id, created_at
                """,
                (
                    uuid4(),
                    conversation_pk,
                    Jsonb(content.model_dump(mode="json")),
                    client_message_id,
                ),
            )
            row = await cursor.fetchone()
        return _message(row) if row else None

    async def insert_assistant_message(
        self,
        *,
        conversation_pk: int,
        reply_to_message_id: UUID,
        content: MessageContent,
    ) -> MessageRecord:
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO conversation_messages (
                    id, conversation_pk, reply_to_message_id, role, content
                )
                VALUES (%s, %s, %s, 'assistant', %s)
                RETURNING sequence, id, conversation_pk, reply_to_message_id,
                          role, content, client_message_id, created_at
                """,
                (
                    uuid4(),
                    conversation_pk,
                    reply_to_message_id,
                    Jsonb(content.model_dump(mode="json")),
                ),
            )
            row = await cursor.fetchone()
            await connection.execute(
                "UPDATE conversations SET updated_at = now() WHERE pk = %s",
                (conversation_pk,),
            )
        return _message(row)

    async def delete(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
    ) -> bool:
        async with self._database.connection() as connection:
            cursor = await connection.execute(
                """
                DELETE FROM conversations
                WHERE user_id = %s AND id = %s
                RETURNING pk
                """,
                (user_id, conversation_id),
            )
            row = await cursor.fetchone()
        return row is not None
