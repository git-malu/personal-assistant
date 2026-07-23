from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from tests.conftest import PostgresTestSchema

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database: PostgresTestSchema) -> Config:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.attributes["dsn"] = database.dsn
    config.attributes["schema"] = database.name
    return config


def _fetch_value(
    database: PostgresTestSchema,
    query: str,
    parameters: tuple[object, ...] = (),
) -> object:
    with (
        psycopg.connect(database.dsn) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(query, parameters)
        return cursor.fetchone()[0]


@pytest.mark.integration
@pytest.mark.postgres
def test_upgrade_head_initializes_empty_schema(postgres_schema: PostgresTestSchema):
    command.upgrade(_alembic_config(postgres_schema), "head")

    with (
        psycopg.connect(postgres_schema.dsn) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
            """,
            (postgres_schema.name,),
        )
        tables = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'oauth2_callback_states'
              AND column_name = 'session_id'
            """,
            (postgres_schema.name,),
        )
        session_id_nullable = cursor.fetchone()[0]

    assert tables == {
        "alembic_version",
        "conversation_messages",
        "conversations",
        "oauth2_callback_states",
    }
    assert session_id_nullable == "YES"


@pytest.mark.integration
@pytest.mark.postgres
def test_upgrade_preserves_legacy_oauth_rows(postgres_schema: PostgresTestSchema):
    with psycopg.connect(postgres_schema.dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE TABLE {}.oauth2_callback_states (
                    nonce TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            ).format(sql.Identifier(postgres_schema.name))
        )
        connection.execute(
            sql.SQL(
                """
                INSERT INTO {}.oauth2_callback_states (
                    nonce, provider, user_id, session_id, status, expires_at
                )
                VALUES ('legacy', 'calendar', 'user-1', 'runtime-1', 'active', now())
                """
            ).format(sql.Identifier(postgres_schema.name))
        )

    command.upgrade(_alembic_config(postgres_schema), "head")

    with (
        psycopg.connect(postgres_schema.dsn) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL("SELECT nonce, session_id FROM {}.oauth2_callback_states").format(
                sql.Identifier(postgres_schema.name)
            )
        )
        row = cursor.fetchone()

    assert row == ("legacy", "runtime-1")
    assert (
        _fetch_value(
            postgres_schema,
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'oauth2_callback_states'
              AND column_name = 'session_id'
            """,
            (postgres_schema.name,),
        )
        == "YES"
    )


@pytest.mark.integration
@pytest.mark.postgres
def test_upgrade_head_is_idempotent(postgres_schema: PostgresTestSchema):
    config = _alembic_config(postgres_schema)

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    assert (
        _fetch_value(
            postgres_schema,
            f'SELECT count(*) FROM "{postgres_schema.name}".alembic_version '
            "WHERE version_num = '20260714_02_conversations'",
        )
        == 1
    )


@pytest.mark.integration
@pytest.mark.postgres
def test_upgrade_rejects_incompatible_legacy_oauth_schema(
    postgres_schema: PostgresTestSchema,
):
    with psycopg.connect(postgres_schema.dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE TABLE {}.oauth2_callback_states (
                    nonce TEXT PRIMARY KEY,
                    provider INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            ).format(sql.Identifier(postgres_schema.name))
        )

    with pytest.raises(RuntimeError, match="provider.*PostgreSQL TEXT"):
        command.upgrade(_alembic_config(postgres_schema), "head")
