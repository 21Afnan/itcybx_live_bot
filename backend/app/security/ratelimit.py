"""Message limits, counted in Redis (PLAN.md: 20 messages per 10 minutes).

Each limit is a counter that starts at the first message and resets when
its window ends. Counted per visitor IP and per chat, so neither a single
browser nor many chats from one place can flood the bot.
"""

from app import sessions
from app.config import settings


async def allow(key: str, limit: int | None = None, window: int | None = None) -> bool:
    """Count one request for `key`. False once the limit is reached in this window."""
    limit = limit or settings.rate_limit_messages
    window = window or settings.rate_limit_window_seconds
    redis = sessions.get_redis()
    count = await redis.incr(f"ratelimit:{key}")
    if count == 1:
        await redis.expire(f"ratelimit:{key}", window)
    return count <= limit
