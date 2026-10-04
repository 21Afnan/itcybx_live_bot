"""Background jobs that run inside the API process.

    weekly        website sync on SYNC_CRON (app/knowledge/sync.py)
    at start-up   the same sync once, in production: a redeploy can bring
                  back older knowledge files than the live website
    hourly        resend lead alerts that didn't go out (app/leads/notify.py)

With several API workers each one starts this scheduler, so every job
first takes a short Redis lock and only one worker runs it.
"""

import logging
from datetime import datetime, timedelta, timezone

from app import sessions
from app.config import settings
from app.knowledge.sync import cron_trigger, scheduled_sync
from app.leads.notify import retry_unsent_alerts

log = logging.getLogger("chatbot.jobs")

STARTUP_SYNC_DELAY = timedelta(seconds=60)  # let the server settle first


async def run_once(name: str, job, lock_seconds: int) -> None:
    """Run `job` unless another worker started it within `lock_seconds`."""
    try:
        if not await sessions.get_redis().set(f"job:lock:{name}", "1", nx=True, ex=lock_seconds):
            return
    except Exception:
        log.warning("Redis unavailable, running %s without a lock", name)
    await job()


def start_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def weekly_sync():
        await run_once("sync", scheduled_sync, lock_seconds=600)

    async def startup_sync():
        # No email: the changes only bring the files back to the live website.
        await run_once("sync", lambda: scheduled_sync(notify=False), lock_seconds=600)

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
