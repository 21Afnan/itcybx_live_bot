"""The API server. For now it has one page: /health."""

import asyncio
from functools import lru_cache

from fastapi import FastAPI, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

CHECK_TIMEOUT_SECONDS = 10  # the first connection to Supabase can take a few seconds

app = FastAPI(title="IT Cybx Chatbot")


@lru_cache
def get_database() -> AsyncEngine:
    """Connection to Supabase, created on first use.

    Created lazily so a wrong DATABASE_URL shows up in /health
    instead of stopping the whole app from starting.
    """
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_redis() -> Redis:
    """Connection to Redis, created on first use."""
    return Redis.from_url(settings.redis_url, socket_timeout=3)


async def database_status() -> str:
    """Ask Supabase a tiny question. "ok", or the error's type name."""

    async def ping():
        async with get_database().connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(ping(), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as e:
        return type(e).__name__  # never the message: it may contain the connection string


async def redis_status() -> str:
    """Ping Redis. "ok", or the error's type name."""
    try:
        await asyncio.wait_for(get_redis().ping(), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception as e:
        return type(e).__name__


@app.get("/health")
async def health(response: Response):
    """Say whether Supabase and Redis are working."""
    db = await database_status()
    redis = await redis_status()
    all_ok = db == "ok" and redis == "ok"

    if not all_ok:
        response.status_code = 503  # tells uptime monitors something is wrong

    return {"status": "ok" if all_ok else "degraded", "db": db, "redis": redis}
