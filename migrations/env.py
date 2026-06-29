"""Alembic environment (async).

Pulls the database URL from application settings and uses the ORM metadata as
the autogenerate target, so future schema changes can be generated with
`alembic revision --autogenerate`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from src.config import get_settings

# Import models so they register on Base.metadata.
from src.infrastructure.persistence import models  # noqa: F401
from src.infrastructure.persistence.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Used by offline mode only; online mode builds the async engine directly below
# so it can pass asyncpg-safe connect args (TLS for managed Postgres).
config.set_main_option("sqlalchemy.url", get_settings().database_url_async)
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = get_settings()
    connectable = create_async_engine(
        settings.database_url_async,
        connect_args=settings.database_connect_args,
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
