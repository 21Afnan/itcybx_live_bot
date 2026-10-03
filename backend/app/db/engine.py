"""The connection to Supabase, shared by the whole app."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Created on first use, so a wrong DATABASE_URL shows up in /health
    instead of stopping the whole app from starting."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


def db_session():
    """A database session: `async with db_session() as db: ...`"""
    return async_sessionmaker(get_engine(), expire_on_commit=False)()
