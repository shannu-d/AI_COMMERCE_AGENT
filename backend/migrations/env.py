"""Alembic environment.

Two things are worth knowing about this file.

**The URL comes from application settings**, not from ``alembic.ini``, so a
database password is never written to a committed file and migrations always
target the same database the application does.

**Offline mode is fully supported.** ``alembic upgrade head --sql`` renders the
complete DDL without connecting to anything. That is how the schema is verified
on a machine with no PostgreSQL server: the migration scripts really execute,
and the exact PostgreSQL DDL they produce can be inspected and asserted against.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# The backend directory, so ``app`` is importable when Alembic is invoked from
# anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing the models package registers every table on Base.metadata.
# Without this import, autogenerate would see an empty schema.
import app.db.models  # noqa: F401
from app.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Prefer an explicit ``-x url=...``, then settings.

    The override exists so tests can point a migration run at a throwaway
    database without mutating the process environment.
    """
    overrides = context.get_x_argument(as_dictionary=True)
    if "url" in overrides:
        return overrides["url"]
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Execute migrations against a live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
