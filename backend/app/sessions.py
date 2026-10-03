"""The bot's memory of each chat between messages, kept in Redis.

Redis is fast but short-lived. Every message is also saved in Supabase, so
if Redis forgets a chat the API rebuilds it from there (app/db/repo.py).
"""

import json
from functools import lru_cache

from redis.asyncio import Redis

from app.config import settings
from app.graph.state import ChatState

STATE_TTL_SECONDS = 7 * 24 * 3600
LOCK_SECONDS = 60
SAVED_FIELDS = ["session_id", "language", "name", "messages", "summary", "lead",
                "lead_status", "capture_asks", "qualify_asked", "last_step"]


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, socket_timeout=3, decode_responses=True)


async def load(session_id: str) -> ChatState | None:
    raw = await get_redis().get(f"chat:state:{session_id}")
    return json.loads(raw) if raw else None


async def save(state: ChatState) -> None:
    data = {field: state.get(field) for field in SAVED_FIELDS}
    await get_redis().set(
        f"chat:state:{state['session_id']}", json.dumps(data, ensure_ascii=False),
        ex=STATE_TTL_SECONDS,
    )


async def lock(session_id: str) -> bool:
    """Only one message per chat at a time. False if one is already running."""
    return bool(await get_redis().set(f"chat:lock:{session_id}", "1", nx=True, ex=LOCK_SECONDS))


async def unlock(session_id: str) -> None:
    await get_redis().delete(f"chat:lock:{session_id}")
