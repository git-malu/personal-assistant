"""SQLAlchemy database configuration shared by migrations and tooling."""

from sqlalchemy.engine import URL, make_url


def sqlalchemy_database_url(dsn: str) -> URL:
    """Normalize an application PostgreSQL DSN for SQLAlchemy + psycopg 3."""
    url = make_url(dsn)
    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+psycopg")
    if url.drivername not in {"postgresql+psycopg", "postgresql+psycopg_async"}:
        raise ValueError("POSTGRES_DSN must use PostgreSQL with psycopg 3")
    return url
