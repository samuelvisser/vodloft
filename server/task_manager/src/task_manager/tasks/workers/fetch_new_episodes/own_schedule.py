"""Collections checked on their own schedule, chosen on the Collection's edit page.

Each one gets its own scheduler job that finds new episodes in only that Collection; the regular checks leave it
alone. The jobs follow the Collection: they are made when VODLoft starts and changed when the Collection is.
"""
from __future__ import annotations

import logging
from typing import Any

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from backend.db.models import Collection
from backend.types.collection_types import CheckFrequency
from config import get_settings
from controller.db_utils import db_session
from task_manager.events.registry import VodloftEventLinker
from task_manager.scheduler.executor import execute_task
from task_manager.scheduler.scheduler import start_scheduler

logger = logging.getLogger(__name__)


def own_check_job_id(collection_id: int) -> str:
    return f"own-check-collection-{collection_id}"


def schedule_own_check(collection_id: int, cron: str | None) -> None:
    """Check the Collection on ``cron``; None removes its own schedule."""
    scheduler = start_scheduler()
    job_id = own_check_job_id(collection_id)
    if not cron:
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            pass
        return
    try:
        trigger = CronTrigger.from_crontab(cron, timezone=get_settings().timezone)
    except (TypeError, ValueError) as exc:
        logger.error("Cannot check Collection %s on its own schedule %r: %s", collection_id, cron, exc)
        return
    scheduler.add_job(
        execute_task,
        trigger=trigger,
        kwargs={
            "def_key": "fetch_new_episodes",
            "resource_type": "collection",
            "resource_id": collection_id,
            "schedule_id": None,
            "max_retries": 0,
        },
        id=job_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


def _sync(collection_id: int) -> None:
    with db_session() as s:
        collection = s.get(Collection, collection_id)
        cron = collection.check_cron if collection and collection.check_frequency == CheckFrequency.OWN else None
    schedule_own_check(collection_id, cron)


def _on_collection_changed(**event_data: Any) -> None:
    collection_id = event_data.get("resource_id") or event_data.get("id")
    if collection_id is not None:
        _sync(int(collection_id))


def _on_startup(**_: Any) -> None:
    with db_session() as s:
        own = s.execute(
            select(Collection.id, Collection.check_cron).where(Collection.check_frequency == CheckFrequency.OWN.value)
        ).all()
    for collection_id, cron in own:
        schedule_own_check(collection_id, cron)


def register_own_check_handlers() -> None:
    VodloftEventLinker.subscribe("app.startup", event_callback=_on_startup)
    VodloftEventLinker.subscribe("collection.updated", event_callback=_on_collection_changed)
    VodloftEventLinker.subscribe("collection.deleted", event_callback=_on_collection_changed)
