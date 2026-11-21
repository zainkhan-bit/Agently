"""Alembic environment.

The database URL comes from application settings, never from alembic.ini. Tests (and other
callers) may instead pass an open connection via ``config.attributes["connection"]``.
"""

import sys
from logging.config import fileConfig

from alembic import context

from app.core.database import DatabaseNotConfiguredError, get_engine
from app.models import Base

config = context.config

# Only configure logging when run from the CLI; programmatic callers (tests) keep theirs.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    try:
        engine = get_engine()
    except DatabaseNotConfiguredError:
        sys.exit("DATABASE_URL is not configured; set it in the environment or backend/.env")
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    sys.exit("Offline (--sql) migrations are not supported; run against a database.")
run_migrations_online()
