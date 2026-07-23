from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.invocations.registry import (
    InvocationKey,
    InvocationRegistry,
    ReservationResult,
)


class FakeExecution:
    def __init__(self) -> None:
        self.cancel_requested = False
        self.closed = asyncio.Event()

    def request_cancel(self) -> None:
        self.cancel_requested = True

    async def cancel(self) -> None:
        self.request_cancel()
        await self.closed.wait()


def _key() -> InvocationKey:
    return InvocationKey(
        user_id="user-1",
        conversation_id=uuid4(),
        client_message_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_cancel_waits_for_reserved_execution_to_register_and_close() -> None:
    registry = InvocationRegistry()
    key = _key()
    execution = FakeExecution()
    assert registry.reserve(key=key) is ReservationResult.RESERVED

    cancellation = asyncio.create_task(registry.cancel(key=key))
    await asyncio.sleep(0)
    assert not cancellation.done()

    registry.register(key=key, execution=execution)
    assert execution.cancel_requested
    execution.closed.set()

    assert await cancellation is True
    registry.unregister(key=key, execution=execution)


@pytest.mark.asyncio
async def test_cancel_before_reservation_leaves_reusable_tombstone() -> None:
    registry = InvocationRegistry()
    key = _key()

    assert await registry.cancel(key=key) is False
    assert registry.reserve(key=key) is ReservationResult.CANCELLED
    assert registry.reserve(key=key) is ReservationResult.CANCELLED
