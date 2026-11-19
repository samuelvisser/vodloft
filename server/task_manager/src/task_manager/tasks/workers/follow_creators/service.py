"""Following creators: the daily look for new sections."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Creator
from backend.services.creators import follow_creator
from backend.services.notifications.emitters import creator_sections_found
from sources import CreatorDetails, get_source
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)


def _look_up(s: Session, creator_id: int) -> tuple[str, CreatorDetails] | None:
    creator = s.get(Creator, creator_id)
    if creator is None:
        return None
    title, source_key, ref = creator.title, creator.source_key, creator.url or creator.site_ref
    # No transaction stays open while the Source looks the creator up.
    s.rollback()
    return title, get_source(source_key).creator_details(ref)


def run_follow_creators(s: Session, *, creator_id: int | None = None) -> TaskResult:
    ids = [creator_id] if creator_id is not None else list(s.scalars(select(Creator.id).order_by(Creator.id)))
    s.rollback()
    found = added = 0
    failed: list[str] = []
    for one in ids:
        try:
            looked_up = _look_up(s, one)
        except Exception as exc:  # A Site that is down for one creator must not stop the others.
            logger.warning("Could not look at creator %s: %s", one, exc)
            failed.append(str(one))
            s.rollback()
            continue
        if looked_up is None:
            continue
        _title, details = looked_up

        def save(w: Session, creator_id: int = one, details: CreatorDetails = details):
            creator = w.get(Creator, creator_id)
            if creator is None:
                return None
            result = follow_creator(w, creator, details, now=datetime.now(timezone.utc))
            creator_sections_found(w, creator, result.asked)
            return result

        result = run_write_transaction(save)
        if result is not None:
            found += len(result.asked) + len(result.added) + len(result.ignored)
            added += len(result.added)
    summary = f"Looked at {len(ids) - len(failed)} {'creator' if len(ids) - len(failed) == 1 else 'creators'}"
    if found:
        summary += f", found {found} new {'section' if found == 1 else 'sections'} and added {added}"
    if failed:
        summary += f"; {len(failed)} could not be reached"
    return TaskResult(summary=summary, data={"creators": len(ids), "found": found, "added": added, "failed": failed})
