"""Create or drop an isolated PostgreSQL schema for process-level E2E."""

import argparse
import os
import re

import psycopg
from psycopg import sql

SCHEMA_PATTERN = re.compile(r"^pa_e2e_[0-9a-f]{32}$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "drop"))
    parser.add_argument("schema")
    arguments = parser.parse_args()
    if not SCHEMA_PATTERN.fullmatch(arguments.schema):
        raise ValueError("invalid E2E schema name")

    dsn = os.environ["TEST_POSTGRES_DSN"]
    statement = (
        sql.SQL("CREATE SCHEMA {}")
        if arguments.action == "create"
        else sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(statement.format(sql.Identifier(arguments.schema)))


if __name__ == "__main__":
    main()
