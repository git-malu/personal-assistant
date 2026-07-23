"""Add conversations and conversation messages.

Revision ID: 20260714_02_conversations
Revises: 20260714_01_app_schema_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_02_conversations"
down_revision: str | Sequence[str] | None = "20260714_01_app_schema_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str | None:
    return op.get_context().config.attributes.get("schema")


def _reference(schema: str | None, table: str, column: str) -> str:
    prefix = f"{schema}." if schema else ""
    return f"{prefix}{table}.{column}"


def upgrade() -> None:
    schema = _schema()
    op.create_table(
        "conversations",
        sa.Column(
            "pk",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
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
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name="conversations_title_length_check",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="conversations_status_check",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND archived_at IS NULL) "
            "OR (status = 'archived' AND archived_at IS NOT NULL)",
            name="conversations_archive_state_check",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id",
            name="conversations_user_id_id_key",
        ),
        schema=schema,
    )
    op.create_index(
        "conversations_user_status_updated_idx",
        "conversations",
        ["user_id", "status", sa.text("updated_at DESC"), sa.text("id DESC")],
        schema=schema,
    )

    op.create_table(
        "conversation_messages",
        sa.Column(
            "sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("conversation_pk", sa.BigInteger(), nullable=False),
        sa.Column(
            "reply_to_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "client_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="conversation_messages_role_check",
        ),
        sa.CheckConstraint(
            "(role = 'user' AND client_message_id IS NOT NULL "
            "AND reply_to_message_id IS NULL) "
            "OR (role = 'assistant' AND client_message_id IS NULL "
            "AND reply_to_message_id IS NOT NULL)",
            name="conversation_messages_shape_check",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_pk"],
            [_reference(schema, "conversations", "pk")],
            name="conversation_messages_conversation_pk_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"],
            [_reference(schema, "conversation_messages", "id")],
            name="conversation_messages_reply_to_message_id_fkey",
        ),
        schema=schema,
    )
    op.create_index(
        "conversation_messages_page_idx",
        "conversation_messages",
        ["conversation_pk", "sequence"],
        schema=schema,
    )
    op.create_index(
        "conversation_messages_client_user_idx",
        "conversation_messages",
        ["conversation_pk", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("role = 'user'"),
        schema=schema,
    )
    op.create_index(
        "conversation_messages_assistant_reply_idx",
        "conversation_messages",
        ["reply_to_message_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant'"),
        schema=schema,
    )


def downgrade() -> None:
    raise RuntimeError("application schema downgrades are intentionally unsupported")
