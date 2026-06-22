from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.conversations import assert_conversation_owner
from app.settings import Settings


@pytest.mark.asyncio
async def test_local_mode_validates_uuid_without_database():
    await assert_conversation_owner(
        Settings(_env_file=None),
        "user-1",
        "11111111-1111-4111-8111-111111111111",
    )


@pytest.mark.asyncio
async def test_invalid_conversation_id_returns_400():
    with pytest.raises(HTTPException) as exc:
        await assert_conversation_owner(
            Settings(_env_file=None),
            "user-1",
            "not-a-uuid",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_postgres_owner_miss_returns_404():
    settings = Settings(
        _env_file=None,
        postgres_dsn="postgresql://localhost/test",
    )
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=None)
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    connection = MagicMock()
    connection.cursor.return_value = cursor
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "psycopg.AsyncConnection.connect",
            new=AsyncMock(return_value=connection),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await assert_conversation_owner(
            settings,
            "user-1",
            "11111111-1111-4111-8111-111111111111",
        )
    assert exc.value.status_code == 404
