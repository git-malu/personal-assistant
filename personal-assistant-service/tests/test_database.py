import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database import sqlalchemy_database_url
from app.db_models import Base


def test_sqlalchemy_database_url_uses_psycopg_3():
    url = sqlalchemy_database_url(
        "postgresql://pa_app:secret@db.example.com/personal_assistant"
    )

    assert url.drivername == "postgresql+psycopg"
    assert url.database == "personal_assistant"


def test_sqlalchemy_database_url_rejects_other_databases():
    with pytest.raises(ValueError, match="PostgreSQL"):
        sqlalchemy_database_url("sqlite:///local.db")


def test_application_metadata_contains_feature_14_tables():
    assert set(Base.metadata.tables) == {
        "conversations",
        "conversation_messages",
        "runtime_session_leases",
        "legacy_session_migrations",
    }


def test_conversation_ddl_contains_postgresql_constraints():
    ddl = str(
        CreateTable(Base.metadata.tables["conversation_messages"]).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "JSONB" in ddl
    assert "ON DELETE CASCADE" in ddl
    assert "conversation_messages_status_ck" in ddl
