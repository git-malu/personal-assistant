from __future__ import annotations

import asyncio
import os
import selectors
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql


@dataclass(frozen=True)
class PostgresTestSchema:
    dsn: str
    name: str


def pytest_asyncio_loop_factories(config, item):
    del config, item
    if sys.platform == "win32":
        return {
            "selector": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        }
    return {"default": asyncio.new_event_loop}


@pytest.fixture
def postgres_schema() -> Iterator[PostgresTestSchema]:
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")

    schema = f"pa_test_{uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    try:
        yield PostgresTestSchema(dsn=dsn, name=schema)
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
