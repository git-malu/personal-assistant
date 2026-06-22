"""Create Feature 14 conversation and runtime lease tables.

Revision ID: 0001_feature_14
Revises:
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_feature_14"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "title",
            sa.Text(),
            server_default="新对话",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="regular",
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('regular', 'archived', 'deleted')",
            name="conversations_status_ck",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "conversations_user_idempotency_key_uq",
        "conversations",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "conversations_user_updated_idx",
        "conversations",
        ["user_id", "status", sa.text("updated_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default="complete",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="conversation_messages_role_ck",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'complete', 'failed', 'uncertain')",
            name="conversation_messages_status_ck",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="conversation_messages_conversation_sequence_uq",
        ),
    )
    op.create_index(
        "conversation_messages_page_idx",
        "conversation_messages",
        ["conversation_id", sa.text("sequence DESC")],
    )

    op.create_table(
        "runtime_session_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("runtime_session_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Text(),
            server_default="explicit",
            nullable=False,
        ),
        sa.Column(
            "owner_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_latency_ms", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('starting', 'active', 'degraded', 'expired', "
            "'stopping', 'stopped', 'stop_failed')",
            name="runtime_session_leases_status_ck",
        ),
        sa.CheckConstraint(
            "source IN ('explicit', 'implicit')",
            name="runtime_session_leases_source_ck",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runtime_session_id"),
    )
    op.create_index(
        "runtime_session_user_active_uq",
        "runtime_session_leases",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('starting', 'active')"),
    )

    op.create_table(
        "legacy_session_migrations",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("legacy_session_hash", sa.Text(), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'complete', 'failed')",
            name="legacy_session_migrations_status_ck",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "legacy_session_hash"),
    )


def downgrade() -> None:
    op.drop_table("legacy_session_migrations")
    op.drop_index(
        "runtime_session_user_active_uq",
        table_name="runtime_session_leases",
    )
    op.drop_table("runtime_session_leases")
    op.drop_index(
        "conversation_messages_page_idx",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index(
        "conversations_user_updated_idx",
        table_name="conversations",
    )
    op.drop_index(
        "conversations_user_idempotency_key_uq",
        table_name="conversations",
    )
    op.drop_table("conversations")
