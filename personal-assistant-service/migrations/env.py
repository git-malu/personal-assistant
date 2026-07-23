from __future__ import annotations

import os
import re
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None
_SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


def _database_url() -> str:
    dsn = config.attributes.get("dsn") or os.getenv("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is required to run database migrations")
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+psycopg://", 1)
    return dsn


def _schema() -> str | None:
    schema = config.attributes.get("schema")
    if schema is not None and not _SCHEMA_PATTERN.fullmatch(schema):
        raise RuntimeError(f"invalid migration schema: {schema!r}")
    return schema


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    schema = _schema()
    engine = sa.create_engine(_database_url(), poolclass=sa.pool.NullPool)

    with engine.connect() as connection:
        if schema:
            connection.execute(sa.text(f'SET search_path TO "{schema}"'))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema,
        )

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
