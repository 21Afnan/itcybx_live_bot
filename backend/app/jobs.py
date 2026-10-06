"""Background jobs that run inside the API process.

    weekly        website sync on SYNC_CRON (app/knowledge/sync.py)
    at start-up   the same sync once, in production: a redeploy can bring
                  back older knowledge files than the live website
    hourly        resend lead alerts that didn't go out (app/leads/notify.py)

With several API workers each one starts this scheduler, so every job
first takes a short Redis lock and only one worker runs it.

The knowledge files live inside each container, so the sync is locked per
container (several workers of one container share its files); with more
than one container each keeps its own files current, and only the first
to sync emails the team about the changes.
"""

import logging
import socket
from datetime import datetime, timedelta, timezone

from app import sessions
from app.config import settings
from app.knowledge.sync import cron_trigger, scheduled_sync
from app.leads.notify import retry_unsent_alerts

log = logging.getLogger("chatbot.jobs")

STARTUP_SYNC_DELAY = timedelta(seconds=60)  # let the server settle first
HOST = socket.gethostname()  # the container's id in Docker


async def claim(name: str, lock_seconds: int) -> bool:
    """True for the first worker to ask within `lock_seconds` (or if Redis is down)."""
    try:
        return bool(await sessions.get_redis().set(f"job:lock:{name}", "1", nx=True, ex=lock_seconds))
    except Exception:
        log.warning("Redis unavailable, running %s without a lock", name)
        return True


async def run_once(name: str, job, lock_seconds: int) -> None:
    """Run `job` unless another worker started it within `lock_seconds`."""
    if await claim(name, lock_seconds):
        await job()


def start_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def weekly_sync():
        async def sync_and_maybe_email():
            await scheduled_sync(notify=await claim("sync-email", lock_seconds=3600))
        await run_once(f"sync:{HOST}", sync_and_maybe_email, lock_seconds=600)

    async def startup_sync():
        # No email: the changes only bring the files back to the live website.
        await run_once(f"sync:{HOST}", lambda: scheduled_sync(notify=False), lock_seconds=600)

    async def lead_alerts():
        await run_once("lead-alerts", retry_unsent_alerts, lock_seconds=50 * 60)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(weekly_sync, cron_trigger(settings.sync_cron), id="weekly-sync",
                      max_instances=1, coalesce=True)
    scheduler.add_job(lead_alerts, "interval", hours=1, id="lead-alerts",
                      max_instances=1, coalesce=True)
    if settings.app_env == "production":
        scheduler.add_job(startup_sync, "date", id="startup-sync",
                          run_date=datetime.now(timezone.utc) + STARTUP_SYNC_DELAY)
    scheduler.start()
    return scheduler
