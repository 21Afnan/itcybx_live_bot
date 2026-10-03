"""Alembic setup: connects to the database in DATABASE_URL and runs migrations."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.models import Base

target_metadata = Base.metadata


def run_offline() -> None:
    """Print the SQL instead of running it (alembic upgrade head --sql)."""
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_sync(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    """Connect to the database and apply the migrations."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
