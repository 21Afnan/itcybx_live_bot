"""The bot's memory of each chat between messages, kept in Redis.

Redis is fast but short-lived. Every message is also saved in Supabase, so
if Redis forgets a chat the API rebuilds it from there (app/db/repo.py).
"""

import json
import uuid
from functools import lru_cache

from redis.asyncio import Redis

from app.config import settings
from app.graph.state import ChatState

STATE_TTL_SECONDS = 7 * 24 * 3600
LOCK_SECONDS = 300
TURN_TIMEOUT_SECONDS = 240  # finish or cancel work before its lease expires
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


async def forget(session_id: str) -> None:
    """Drop the cached state; the next load rebuilds it from Supabase."""
    await get_redis().delete(f"chat:state:{session_id}")


async def lock(session_id: str) -> str | None:
    """Only one message per chat at a time. False if one is already running."""
    token = uuid.uuid4().hex
    acquired = await get_redis().set(f"chat:lock:{session_id}", token, nx=True, ex=LOCK_SECONDS)
    return token if acquired else None


async def unlock(session_id: str, token: str) -> None:
    # A delayed worker must never release another worker's lease.
    await get_redis().eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1, f"chat:lock:{session_id}", token,
    )
