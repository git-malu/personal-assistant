from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class DatabaseUnavailableError(RuntimeError):
    pass


class Database:
    """Application-owned PostgreSQL connection pool."""

    def __init__(
        self,
        dsn: str | None,
        *,
        connection_kwargs: Mapping[str, Any] | None = None,
        max_size: int = 10,
        lock_max_size: int | None = None,
    ) -> None:
        self._pool: AsyncConnectionPool | None = None
        self._lock_pool: AsyncConnectionPool | None = None
        if dsn:
            kwargs: dict[str, Any] = {
                "autocommit": False,
                "row_factory": dict_row,
            }
            if connection_kwargs:
                kwargs.update(connection_kwargs)
            self._pool = AsyncConnectionPool(
                conninfo=dsn,
                kwargs=kwargs,
                min_size=0,
                max_size=max_size,
                open=False,
                name="personal-assistant-app",
            )
            self._lock_pool = AsyncConnectionPool(
                conninfo=dsn,
                kwargs=kwargs,
                min_size=0,
                max_size=lock_max_size or max_size,
                open=False,
                name="personal-assistant-locks",
            )

    @property
    def available(self) -> bool:
        return self._pool is not None

    async def startup(self) -> None:
        if self._pool is not None:
            await self._pool.open(wait=True)
        if self._lock_pool is not None:
            try:
                await self._lock_pool.open(wait=True)
            except BaseException:
                if self._pool is not None:
                    await self._pool.close()
                raise

    async def shutdown(self) -> None:
        if self._lock_pool is not None:
            await self._lock_pool.close()
        if self._pool is not None:
            await self._pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._pool is None:
            raise DatabaseUnavailableError("PostgreSQL is not configured")
        async with self._pool.connection() as connection:
            yield connection

    @asynccontextmanager
    async def lock_connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._lock_pool is None:
            raise DatabaseUnavailableError("PostgreSQL is not configured")
        async with self._lock_pool.connection() as connection:
            yield connection
