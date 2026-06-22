"""SQLAlchemy metadata for Personal Assistant-owned PostgreSQL tables."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for application-owned relational models."""


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('regular', 'archived', 'deleted')",
            name="conversations_status_ck",
        ),
        Index(
            "conversations_user_idempotency_key_uq",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "conversations_user_updated_idx",
            "user_id",
            "status",
            text("updated_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, server_default="新对话")
    status: Mapped[str] = mapped_column(Text, server_default="regular")
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="conversation_messages_role_ck",
        ),
        CheckConstraint(
            "status IN ('pending', 'complete', 'failed', 'uncertain')",
            name="conversation_messages_status_ck",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="conversation_messages_conversation_sequence_uq",
        ),
        Index(
            "conversation_messages_page_idx",
            "conversation_id",
            text("sequence DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    parent_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[Any] = mapped_column(JSONB)
    sequence: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, server_default="complete")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class RuntimeSessionLease(Base):
    __tablename__ = "runtime_session_leases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('starting', 'active', 'degraded', 'expired', "
            "'stopping', 'stopped', 'stop_failed')",
            name="runtime_session_leases_status_ck",
        ),
        CheckConstraint(
            "source IN ('explicit', 'implicit')",
            name="runtime_session_leases_source_ck",
        ),
        Index(
            "runtime_session_user_active_uq",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('starting', 'active')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(Text)
    runtime_session_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="explicit")
    owner_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_latency_ms: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class LegacySessionMigration(Base):
    __tablename__ = "legacy_session_migrations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'complete', 'failed')",
            name="legacy_session_migrations_status_ck",
        ),
    )

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    legacy_session_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id"),
    )
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
