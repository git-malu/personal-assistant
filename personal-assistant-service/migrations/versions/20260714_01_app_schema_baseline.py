"""Baseline the application-owned OAuth callback schema.

Revision ID: 20260714_01_app_schema_baseline
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_01_app_schema_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oauth2_callback_states"
_REQUIRED_COLUMNS = {
    "nonce",
    "provider",
    "user_id",
    "session_id",
    "status",
    "expires_at",
    "created_at",
    "updated_at",
    "completed_at",
}
_TEXT_COLUMNS = {"nonce", "provider", "user_id", "session_id", "status"}
_TIMESTAMP_COLUMNS = {
    "expires_at",
    "created_at",
    "updated_at",
    "completed_at",
}
_NULLABLE_COLUMNS = {"session_id", "completed_at"}


def _schema() -> str | None:
    return op.get_context().config.attributes.get("schema")


def _create_table(schema: str | None) -> None:
    op.create_table(
        _TABLE,
        sa.Column("nonce", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'completed')",
            name="oauth2_callback_states_status_check",
        ),
        schema=schema,
    )


def _validate_existing_table(
    inspector: sa.Inspector,
    schema: str | None,
) -> None:
    columns = {
        column["name"]: column
        for column in inspector.get_columns(_TABLE, schema=schema)
    }
    missing = sorted(_REQUIRED_COLUMNS - columns.keys())
    if missing:
        raise RuntimeError(
            f"existing {_TABLE} table is missing required columns: {missing}"
        )

    for name in _TEXT_COLUMNS:
        if not isinstance(columns[name]["type"], sa.Text):
            raise RuntimeError(
                f"existing {_TABLE}.{name} column must use the PostgreSQL TEXT type"
            )
    for name in _TIMESTAMP_COLUMNS:
        column_type = columns[name]["type"]
        if not isinstance(column_type, sa.DateTime) or not column_type.timezone:
            raise RuntimeError(f"existing {_TABLE}.{name} column must use TIMESTAMPTZ")

    for name, column in columns.items():
        if name == "session_id":
            continue
        expected_nullable = name in _NULLABLE_COLUMNS
        if column["nullable"] is not expected_nullable:
            raise RuntimeError(
                f"existing {_TABLE}.{name} column has incompatible nullability"
            )

    primary_key = inspector.get_pk_constraint(_TABLE, schema=schema)
    if primary_key.get("constrained_columns") != ["nonce"]:
        raise RuntimeError(f"existing {_TABLE} table has an incompatible primary key")

    checks = inspector.get_check_constraints(_TABLE, schema=schema)
    status_checks = " ".join(
        str(constraint.get("sqltext", "")).lower() for constraint in checks
    )
    if not all(token in status_checks for token in ("status", "active", "completed")):
        raise RuntimeError(f"existing {_TABLE} table has an incompatible status check")

    if not columns["session_id"]["nullable"]:
        op.alter_column(
            _TABLE,
            "session_id",
            existing_type=sa.Text(),
            nullable=True,
            schema=schema,
        )


def upgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())

    if _TABLE not in inspector.get_table_names(schema=schema):
        _create_table(schema)
        existing_indexes: set[str] = set()
    else:
        _validate_existing_table(inspector, schema)
        existing_indexes = {
            index["name"]
            for index in inspector.get_indexes(_TABLE, schema=schema)
            if index.get("name")
        }

    index_name = "idx_oauth2_callback_states_expires_at"
    if index_name not in existing_indexes:
        op.create_index(
            index_name,
            _TABLE,
            ["expires_at"],
            unique=False,
            schema=schema,
        )


def downgrade() -> None:
    raise RuntimeError("application schema downgrades are intentionally unsupported")
