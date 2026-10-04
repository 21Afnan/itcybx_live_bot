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
    # Count and set the expiry in one step, so a crash in between can't leave
    # a counter that never resets. NX: the window starts at the first message.
    async with sessions.get_redis().pipeline(transaction=True) as pipe:
        pipe.incr(f"ratelimit:{key}")
        pipe.expire(f"ratelimit:{key}", window, nx=True)
        count, _ = await pipe.execute()
    return count <= limit
