from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal
from .timeutils import DAILY_RESET_HOUR, effective_reset_date


def should_run_catchup(last_reset_date: str | None, now: datetime) -> bool:
    """Whether a startup catch-up reset is owed for the reset cycle `now` falls in.

    Compares effective reset days, not raw calendar dates, so a restart at 02:00 —
    still inside yesterday's cycle — does not fire a reset an hour before the 03:00
    boundary and wipe live edits on overnight trips.
    """
    return last_reset_date != effective_reset_date(now)


def run_startup_catchup_if_needed(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()
    if should_run_catchup(service.get_last_reset_date(db), now):
        service.perform_daily_reset(db, now=now)


def run_daily_reset_job() -> None:
    db = SessionLocal()
    try:
        service.perform_daily_reset(db)
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_daily_reset_job, CronTrigger(hour=DAILY_RESET_HOUR, minute=0))
    scheduler.start()
    return scheduler
