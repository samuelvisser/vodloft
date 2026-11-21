"""Following creators: the daily look for new sections."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import CreatorAccount
from backend.services.creators import follow_account
from backend.services.notifications.emitters import creator_sections_found
from backend.services.source_options import ytdlp_call_options
from sources import CreatorDetails, get_source
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)


def _look_up(s: Session, account_id: int) -> tuple[str, CreatorDetails] | None:
    account = s.get(CreatorAccount, account_id)
    if account is None:
        return None
    title, source_key, ref = account.creator.title, account.source_key, account.url or account.site_ref
    # No transaction stays open while the Source looks the account up.
    s.rollback()
    with ytdlp_call_options(source_key):
        return title, get_source(source_key).creator_details(ref)


def run_follow_creators(s: Session, *, creator_id: int | None = None) -> TaskResult:
    """Look at each account of every creator, or of the one creator ``creator_id``."""
    query = select(CreatorAccount.id).order_by(CreatorAccount.creator_id, CreatorAccount.id)
    if creator_id is not None:
        query = query.where(CreatorAccount.creator_id == creator_id)
    ids = list(s.scalars(query))
    creators = len(set(s.scalars(select(CreatorAccount.creator_id).where(CreatorAccount.id.in_(ids))))) if ids else 0
    s.rollback()
    found = added = 0
    failed: list[str] = []
    for one in ids:
        try:
            looked_up = _look_up(s, one)
        except Exception as exc:  # A Site that is down for one account must not stop the others.
            logger.warning("Could not look at creator account %s: %s", one, exc)
            failed.append(str(one))
            s.rollback()
            continue
        if looked_up is None:
            continue
        _title, details = looked_up

        def save(w: Session, account_id: int = one, details: CreatorDetails = details):
            account = w.get(CreatorAccount, account_id)
            if account is None:
                return None
            result = follow_account(w, account, details, now=datetime.now(timezone.utc))
            creator_sections_found(w, account.creator, result.asked)
            return result

        result = run_write_transaction(save)
        if result is not None:
            found += len(result.asked) + len(result.added) + len(result.ignored)
            added += len(result.added)
    looked = len(ids) - len(failed)
    summary = f"Looked at {looked} {'account' if looked == 1 else 'accounts'} of {creators} {'creator' if creators == 1 else 'creators'}"
    if found:
        summary += f", found {found} new {'section' if found == 1 else 'sections'} and added {added}"
    if failed:
        summary += f"; {len(failed)} could not be reached"
    return TaskResult(summary=summary, data={"creators": creators, "accounts": len(ids), "found": found, "added": added, "failed": failed})
