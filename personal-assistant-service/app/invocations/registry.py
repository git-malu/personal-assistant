from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.invocations.service import InvocationExecution


@dataclass(frozen=True)
class InvocationKey:
    user_id: str
    conversation_id: UUID
    client_message_id: UUID


class ReservationResult(Enum):
    RESERVED = auto()
    CANCELLED = auto()
    DUPLICATE = auto()


@dataclass
class _InvocationSlot:
    reserved: bool
    execution: InvocationExecution | None = None
    cancel_requested: bool = False
    ready_or_finished: asyncio.Event = field(default_factory=asyncio.Event)
    expiry_handle: asyncio.TimerHandle | None = None


class InvocationRegistry:
    def __init__(self, *, pending_cancellation_ttl_seconds: float = 120.0) -> None:
        self._slots: dict[InvocationKey, _InvocationSlot] = {}
        self._pending_cancellation_ttl_seconds = pending_cancellation_ttl_seconds

    def reserve(self, *, key: InvocationKey) -> ReservationResult:
        slot = self._slots.get(key)
        if slot is None:
            self._slots[key] = _InvocationSlot(reserved=True)
            return ReservationResult.RESERVED
        if not slot.reserved and slot.cancel_requested:
            return ReservationResult.CANCELLED
        return ReservationResult.DUPLICATE

    def register(
        self,
        *,
        key: InvocationKey,
        execution: InvocationExecution,
    ) -> None:
        slot = self._slots.get(key)
        if slot is None or not slot.reserved:
            raise RuntimeError("invocation is not reserved")
        if slot.execution is not None:
            raise RuntimeError("invocation is already registered")
        slot.execution = execution
        slot.ready_or_finished.set()
        if slot.cancel_requested:
            execution.request_cancel()

    def discard(self, *, key: InvocationKey) -> None:
        slot = self._slots.get(key)
        if slot is not None and slot.execution is None:
            self._remove_slot(key=key, slot=slot)

    def unregister(
        self,
        *,
        key: InvocationKey,
        execution: InvocationExecution,
    ) -> None:
        slot = self._slots.get(key)
        if slot is not None and slot.execution is execution:
            self._remove_slot(key=key, slot=slot)

    async def cancel(self, *, key: InvocationKey) -> bool:
        slot = self._slots.get(key)
        if slot is None:
            slot = _InvocationSlot(reserved=False, cancel_requested=True)
            self._slots[key] = slot
            loop = asyncio.get_running_loop()
            slot.expiry_handle = loop.call_later(
                self._pending_cancellation_ttl_seconds,
                self._expire_pending_cancellation,
                key,
                slot,
            )
            return False
        if not slot.reserved:
            return False

        slot.cancel_requested = True
        execution = slot.execution
        if execution is None:
            await slot.ready_or_finished.wait()
            execution = slot.execution
        if execution is None:
            return False
        await execution.cancel()
        return True

    def _expire_pending_cancellation(
        self,
        key: InvocationKey,
        slot: _InvocationSlot,
    ) -> None:
        if self._slots.get(key) is slot:
            self._remove_slot(key=key, slot=slot)

    def _remove_slot(self, *, key: InvocationKey, slot: _InvocationSlot) -> None:
        if self._slots.get(key) is not slot:
            return
        del self._slots[key]
        slot.ready_or_finished.set()
        if slot.expiry_handle is not None:
            slot.expiry_handle.cancel()
            slot.expiry_handle = None
