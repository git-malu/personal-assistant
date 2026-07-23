from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg

from app.database import Database


class ConversationBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConversationLockLease:
    connection: psycopg.AsyncConnection

    async def verify(self) -> None:
        result = await self.connection.execute("SELECT 1 AS healthy")
        row = await result.fetchone()
        await self.connection.commit()
        if row["healthy"] != 1:
            raise RuntimeError("conversation lock connection is unavailable")


class ConversationLock:
    def __init__(self, database: Database) -> None:
        self._database = database

    @asynccontextmanager
    async def acquire(
        self,
        conversation_pk: int,
    ) -> AsyncIterator[ConversationLockLease]:
        async with self._database.lock_connection() as connection:
            result = await connection.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired",
                (conversation_pk,),
            )
            row = await result.fetchone()
            await connection.commit()
            if not row["acquired"]:
                raise ConversationBusyError("conversation is busy")

            try:
                yield ConversationLockLease(connection)
            finally:
                result = await connection.execute(
                    "SELECT pg_advisory_unlock(%s) AS released",
                    (conversation_pk,),
                )
                await result.fetchone()
                await connection.commit()
