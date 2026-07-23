from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from app.conversations.locks import ConversationLock
from app.conversations.models import (
    DEFAULT_CONVERSATION_TITLE,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessageListResponse,
    ConversationMessageResponse,
    ConversationPatchRequest,
    ConversationResponse,
    ConversationStatus,
)
from app.conversations.store import ConversationRecord, ConversationStore


class ConversationNotFoundError(LookupError):
    pass


class InvalidCursorError(ValueError):
    pass


class CheckpointDeleteError(RuntimeError):
    pass


def _encode_conversation_cursor(record: ConversationRecord) -> str:
    payload = json.dumps(
        [record.updated_at.isoformat(), str(record.id)],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _decode_conversation_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        encoded = cursor.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        payload = base64.b64decode(padded, altchars=b"-_", validate=True)
        raw = json.loads(payload)
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError
        updated_at = datetime.fromisoformat(raw[0])
        conversation_id = UUID(raw[1])
        if updated_at.tzinfo is None:
            raise ValueError
    except (
        UnicodeEncodeError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise InvalidCursorError("invalid conversation cursor") from error
    return updated_at, conversation_id


def _decode_message_cursor(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        sequence = int(cursor)
    except ValueError as error:
        raise InvalidCursorError("invalid message cursor") from error
    if sequence < 0 or str(sequence) != cursor:
        raise InvalidCursorError("invalid message cursor")
    return sequence


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        *,
        lock: ConversationLock | None = None,
        checkpointer=None,
    ) -> None:
        self._store = store
        self._lock = lock
        self._checkpointer = checkpointer

    async def create(
        self,
        *,
        user_id: str,
        request: ConversationCreateRequest,
    ) -> ConversationResponse:
        record = await self._store.create(
            user_id=user_id,
            title=request.title or DEFAULT_CONVERSATION_TITLE,
        )
        return ConversationResponse.model_validate(record)

    async def get(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
    ) -> ConversationResponse:
        record = await self._require(user_id=user_id, conversation_id=conversation_id)
        return ConversationResponse.model_validate(record)

    async def list(
        self,
        *,
        user_id: str,
        status: ConversationStatus,
        cursor: str | None,
        limit: int,
    ) -> ConversationListResponse:
        records = await self._store.list(
            user_id=user_id,
            status=status,
            cursor=_decode_conversation_cursor(cursor),
            limit=limit + 1,
        )
        page = records[:limit]
        next_cursor = (
            _encode_conversation_cursor(page[-1])
            if len(records) > limit and page
            else None
        )
        return ConversationListResponse(
            items=[ConversationResponse.model_validate(record) for record in page],
            next_cursor=next_cursor,
        )

    async def patch(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        request: ConversationPatchRequest,
    ) -> ConversationResponse:
        record = await self._store.update(
            user_id=user_id,
            conversation_id=conversation_id,
            title=request.title if "title" in request.model_fields_set else None,
            status=request.status if "status" in request.model_fields_set else None,
        )
        if record is None:
            raise ConversationNotFoundError
        return ConversationResponse.model_validate(record)

    async def list_messages(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> ConversationMessageListResponse:
        conversation = await self._require(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        records = await self._store.list_messages(
            conversation_pk=conversation.pk,
            after_sequence=_decode_message_cursor(cursor),
            limit=limit + 1,
        )
        page = records[:limit]
        return ConversationMessageListResponse(
            items=[
                ConversationMessageResponse.model_validate(record) for record in page
            ],
            next_cursor=(
                str(page[-1].sequence) if len(records) > limit and page else None
            ),
        )

    async def delete(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
    ) -> None:
        if self._checkpointer is None:
            raise CheckpointDeleteError("Checkpoint storage is unavailable")

        conversation = await self._store.get(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        thread_id = f"{user_id}:{conversation_id}"
        if conversation is None:
            await self._delete_checkpoint(thread_id)
            return
        if self._lock is None:
            raise RuntimeError("Conversation lock is unavailable")

        async with self._lock.acquire(conversation.pk):
            await self._store.delete(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            await self._delete_checkpoint(thread_id)

    async def _delete_checkpoint(self, thread_id: str) -> None:
        try:
            await self._checkpointer.adelete_thread(thread_id)
        except Exception as error:
            raise CheckpointDeleteError("Checkpoint cleanup failed") from error

    async def _require(
        self,
        *,
        user_id: str,
        conversation_id: UUID,
    ) -> ConversationRecord:
        record = await self._store.get(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        if record is None:
            raise ConversationNotFoundError
        return record
