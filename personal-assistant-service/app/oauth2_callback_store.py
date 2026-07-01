"""OAuth2 callback replay and concurrency state.

Production uses PostgreSQL so duplicate callbacks are coordinated across
Runtime instances. Local/test runs fall back to the existing in-process guards.
"""

from __future__ import annotations

import logging
from typing import Literal

import psycopg

from app.oauth2_state import (
    OAuth2StateClaims,
    clear_oauth2_state_active,
    is_oauth2_state_completed,
    mark_oauth2_state_active,
    mark_oauth2_state_completed,
)
from app.settings import Settings

logger = logging.getLogger("app.oauth2_callback_store")

CallbackBeginStatus = Literal["started", "active", "completed"]


class OAuth2CallbackStore:
    """Store OAuth2 callback completion state with a PostgreSQL production path."""

    def __init__(self, settings: Settings):
        self._postgres_dsn = settings.postgres_dsn

    async def startup(self) -> None:
        """Create the PostgreSQL table used for callback idempotency."""
        if not self._postgres_dsn:
            return

        async with await psycopg.AsyncConnection.connect(
            self._postgres_dsn,
            autocommit=True,
        ) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth2_callback_states (
                    nonce TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'completed')),
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_oauth2_callback_states_expires_at
                ON oauth2_callback_states (expires_at)
                """
            )

    async def shutdown(self) -> None:
        """Keep lifecycle symmetry with other app resources."""
        return None

    async def begin_completion(
        self,
        claims: OAuth2StateClaims,
    ) -> CallbackBeginStatus:
        """Mark a callback nonce active, or report existing active/completed state."""
        if not self._postgres_dsn:
            if is_oauth2_state_completed(claims):
                return "completed"
            return "started" if mark_oauth2_state_active(claims) else "active"

        async with (
            await psycopg.AsyncConnection.connect(self._postgres_dsn) as conn,
            conn.transaction(),
        ):
            await conn.execute(
                "DELETE FROM oauth2_callback_states WHERE expires_at < now()"
            )
            inserted = await conn.execute(
                """
                INSERT INTO oauth2_callback_states (
                    nonce,
                    provider,
                    user_id,
                    session_id,
                    status,
                    expires_at
                )
                VALUES (%s, %s, %s, %s, 'active', to_timestamp(%s))
                ON CONFLICT (nonce) DO NOTHING
                RETURNING status
                """,
                (
                    claims.nonce,
                    claims.provider,
                    claims.user_id,
                    claims.session_id,
                    claims.exp,
                ),
            )
            if await inserted.fetchone():
                return "started"

            existing = await conn.execute(
                """
                SELECT status
                FROM oauth2_callback_states
                WHERE nonce = %s
                """,
                (claims.nonce,),
            )
            row = await existing.fetchone()

        if row and row[0] == "completed":
            return "completed"
        return "active"

    async def mark_completed(self, claims: OAuth2StateClaims) -> None:
        """Record successful callback completion."""
        if not self._postgres_dsn:
            mark_oauth2_state_completed(claims)
            return

        async with await psycopg.AsyncConnection.connect(
            self._postgres_dsn,
            autocommit=True,
        ) as conn:
            await conn.execute(
                """
                UPDATE oauth2_callback_states
                SET status = 'completed',
                    completed_at = now(),
                    updated_at = now()
                WHERE nonce = %s
                """,
                (claims.nonce,),
            )

    async def clear_active(self, claims: OAuth2StateClaims) -> None:
        """Release an active nonce after a failed completion attempt."""
        if not self._postgres_dsn:
            clear_oauth2_state_active(claims)
            return

        async with await psycopg.AsyncConnection.connect(
            self._postgres_dsn,
            autocommit=True,
        ) as conn:
            await conn.execute(
                """
                DELETE FROM oauth2_callback_states
                WHERE nonce = %s
                  AND status = 'active'
                """,
                (claims.nonce,),
            )
