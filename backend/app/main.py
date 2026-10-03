"""The API server. For now it has one page: /health."""

from fastapi import FastAPI, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

app = FastAPI(title="IT Cybx Chatbot")

database = create_async_engine(settings.database_url)
redis = Redis.from_url(settings.redis_url, socket_timeout=3)


async def database_works() -> bool:
    """Ask Postgres a tiny question. True if it answers."""
    try:
        async with database.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def redis_works() -> bool:
    """Ping Redis. True if it answers."""
    try:
        return await redis.ping()
    except Exception:
        return False


@app.get("/health")
async def health(response: Response):
    """Say whether the database and Redis are working."""
    db_ok = await database_works()
    redis_ok = await redis_works()

    if not (db_ok and redis_ok):
        response.status_code = 503  # tells uptime monitors something is wrong

    return {
        "status": "ok" if db_ok and redis_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
    }
