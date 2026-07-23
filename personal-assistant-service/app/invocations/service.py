from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from app.conversations.locks import ConversationLock, ConversationLockLease
from app.conversations.models import (
    ConversationStatus,
    MessageContent,
    TextMessagePart,
)
from app.conversations.store import ConversationStore, MessageRecord
from app.database import Database
from app.invocations.models import (
    AgentEventType,
    InvocationRequest,
    InvocationResponse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.agent_handler import AgentHandler

logger = logging.getLogger(__name__)


class InvocationConversationNotFoundError(LookupError):
    pass


class ArchivedConversationError(RuntimeError):
    pass


class DuplicateMessageError(RuntimeError):
    pass


class InvocationExecution:
    def __init__(
        self,
        *,
        store: ConversationStore,
        handler: AgentHandler,
        request: InvocationRequest,
        user_id: str,
        conversation_pk: int,
        user_message: MessageRecord,
        lock_context: AbstractAsyncContextManager[ConversationLockLease],
        lock_lease: ConversationLockLease,
    ) -> None:
        self._store = store
        self._handler = handler
        self._request = request
        self._user_id = user_id
        self._conversation_pk = conversation_pk
        self._user_message = user_message
        self._lock_context = lock_context
        self._lock_lease = lock_lease
        self._closed = False
        self._closed_event = asyncio.Event()
        self._running_task: asyncio.Task[object] | None = None
        self._cancel_requested = False
        self.status = "prepared"

    async def run_sync(self) -> InvocationResponse:
        self.status = "running"
        self._bind_current_task()
        try:
            response = await self._handler.handle(
                message=self._request.message,
                user_id=self._user_id,
                conversation_id=str(self._request.conversation_id),
            )
            await self._commit_assistant(response)
            self.status = "success"
            return InvocationResponse(response=response)
        except asyncio.CancelledError:
            self.status = "cancelled"
            raise
        except Exception:
            self.status = "error"
            raise
        finally:
            await self.close()

    async def stream_sse(self) -> AsyncIterator[str]:
        self.status = "running"
        self._bind_current_task()
        tokens: list[str] = []
        try:
            async for event in self._handler.handle_stream(
                message=self._request.message,
                user_id=self._user_id,
                conversation_id=str(self._request.conversation_id),
            ):
                if event.type is AgentEventType.TOKEN:
                    token = event.token or ""
                    if token:
                        tokens.append(token)
                        yield _sse_data({"token": token, "done": False})
                elif event.type is AgentEventType.AUTH_CARD:
                    yield _sse_data(event.data, event="auth_card")
                else:
                    yield _sse_data(event.data)

            response = "".join(tokens)
            if not response:
                raise RuntimeError("Agent returned empty response")
            await self._commit_assistant(response)
            self.status = "success"
            yield _sse_data({"token": "", "done": True})
        except asyncio.CancelledError:
            self.status = "cancelled"
            raise
        except Exception as error:
            self.status = "error"
            logger.exception("Invocation stream execution failed", exc_info=error)
            yield _sse_data(
                {
                    "error": "The assistant could not complete this request.",
                    "done": False,
                }
            )
        finally:
            await self.close()

    async def close(self) -> None:
        if self._closed:
            await self._closed_event.wait()
            return
        self._closed = True
        try:
            await self._lock_context.__aexit__(None, None, None)
        finally:
            self._closed_event.set()

    async def cancel(self) -> None:
        self.request_cancel()
        await self._closed_event.wait()

    def request_cancel(self) -> None:
        self._cancel_requested = True
        task = self._running_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _bind_current_task(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("invocation execution requires an asyncio task")
        self._running_task = task
        if self._cancel_requested:
            task.cancel()

    async def _commit_assistant(self, response: str) -> None:
        if not isinstance(response, str) or not response:
            raise RuntimeError("Agent returned empty response")
        await self._lock_lease.verify()
        await self._store.insert_assistant_message(
            conversation_pk=self._conversation_pk,
            reply_to_message_id=self._user_message.id,
            content=MessageContent(parts=[TextMessagePart(text=response)]),
        )


class InvocationService:
    def __init__(self, database: Database) -> None:
        self._store = ConversationStore(database)
        self._lock = ConversationLock(database)

    async def prepare(
        self,
        *,
        request: InvocationRequest,
        user_id: str,
        handler: AgentHandler,
    ) -> InvocationExecution:
        conversation = await self._store.get(
            user_id=user_id,
            conversation_id=request.conversation_id,
        )
        if conversation is None:
            raise InvocationConversationNotFoundError

        lock_context = self._lock.acquire(conversation.pk)
        lock_lease = await lock_context.__aenter__()
        try:
            current = await self._store.get(
                user_id=user_id,
                conversation_id=request.conversation_id,
            )
            if current is None:
                raise InvocationConversationNotFoundError
            if current.status is ConversationStatus.ARCHIVED:
                raise ArchivedConversationError("conversation is archived")

            user_message = await self._store.insert_user_message(
                conversation_pk=current.pk,
                client_message_id=request.client_message_id,
                content=MessageContent(parts=[TextMessagePart(text=request.message)]),
            )
            if user_message is None:
                raise DuplicateMessageError("client_message_id already exists")
        except BaseException:
            await lock_context.__aexit__(None, None, None)
            raise

        return InvocationExecution(
            store=self._store,
            handler=handler,
            request=request,
            user_id=user_id,
            conversation_pk=current.pk,
            user_message=user_message,
            lock_context=lock_context,
            lock_lease=lock_lease,
        )


def _sse_data(data: object, *, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}data: {payload}\n\n"
