"""Conversation persistence helpers for the Agent execution boundary."""

import hashlib
from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.settings import Settings


async def assert_conversation_owner(
    settings: Settings,
    user_id: str,
    conversation_id: str,
) -> None:
    """Verify ownership when PostgreSQL is configured.

    Local/in-memory development has no shared Conversation store, so the
    Pages Functions BFF remains the only check there. Production uses the
    same PostgreSQL database for a defense-in-depth ownership check.
    """
    try:
        normalized_id = str(UUID(conversation_id))
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="conversation_id must be a UUID",
        ) from error

    if not settings.postgres_dsn:
        return

    from psycopg import AsyncConnection

    async with (
        await AsyncConnection.connect(settings.postgres_dsn) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            """
            SELECT 1
              FROM conversations
             WHERE id = %s AND user_id = %s AND status <> 'deleted'
            """,
            (normalized_id, user_id),
        )
        if await cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )


def _visible_messages(messages: Iterable[Any]) -> list[tuple[str, str, str]]:
    visible: list[tuple[str, str, str]] = []
    for message in messages:
        message_type = getattr(message, "type", "")
        role = {"human": "user", "ai": "assistant"}.get(message_type)
        content = getattr(message, "content", "")
        if role and isinstance(content, str) and content.strip():
            visible.append(
                (
                    str(getattr(message, "id", None) or uuid4()),
                    role,
                    content,
                )
            )
    return visible


async def migrate_legacy_conversation(
    settings: Settings,
    user_id: str,
    legacy_session_id: str,
    state: Any,
) -> dict[str, Any]:
    """Idempotently project a legacy Checkpoint into the UI read model."""
    if not settings.postgres_dsn:
        raise HTTPException(
            status_code=503,
            detail="Legacy migration requires PostgreSQL",
        )
    legacy_hash = hashlib.sha256(legacy_session_id.encode()).hexdigest()
    values = getattr(state, "values", {}) or {}
    messages = _visible_messages(values.get("messages", []))

    from psycopg import AsyncConnection
    from psycopg.types.json import Jsonb

    async with (
        await AsyncConnection.connect(settings.postgres_dsn) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        await cursor.execute(
            """
            SELECT conversation_id, status
              FROM legacy_session_migrations
             WHERE user_id = %s AND legacy_session_hash = %s
            """,
            (user_id, legacy_hash),
        )
        existing = await cursor.fetchone()
        if existing and existing[1] == "complete":
            return {
                "conversation_id": str(existing[0]),
                "migrated": False,
            }

        conversation_id = existing[0] if existing else uuid4()
        title = messages[0][2][:36] if messages else "历史对话"
        await cursor.execute(
            """
            INSERT INTO conversations (id, user_id, title)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (conversation_id, user_id, title),
        )

        parent_id = None
        for sequence, (message_id, role, content) in enumerate(
            messages,
            start=1,
        ):
            await cursor.execute(
                """
                INSERT INTO conversation_messages
                    (id, conversation_id, parent_id, role, content,
                     sequence, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'complete')
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    message_id,
                    conversation_id,
                    parent_id,
                    role,
                    Jsonb([{"type": "text", "text": content}]),
                    sequence,
                ),
            )
            parent_id = message_id

        await cursor.execute(
            """
            INSERT INTO legacy_session_migrations
                (user_id, legacy_session_hash, conversation_id, status)
            VALUES (%s, %s, %s, 'complete')
            ON CONFLICT (user_id, legacy_session_hash)
            DO UPDATE SET conversation_id = EXCLUDED.conversation_id,
                          status = 'complete',
                          error = NULL,
                          updated_at = NOW()
            """,
            (user_id, legacy_hash, conversation_id),
        )
    return {"conversation_id": str(conversation_id), "migrated": True}
