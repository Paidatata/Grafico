from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal


def should_run_catchup(last_reset_date: str | None, now: datetime) -> bool:
    return last_reset_date != now.strftime("%Y-%m-%d")


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
    scheduler.add_job(run_daily_reset_job, CronTrigger(hour=3, minute=0))
    scheduler.start()
    return scheduler
