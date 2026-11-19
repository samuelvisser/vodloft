"""Following channels: the daily look for new sections."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.db.models import Channel
from backend.services.channels import follow_channel
from backend.services.notifications.emitters import channel_sections_found
from sources import ChannelDetails, get_source
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)


def _look_up(s: Session, channel_id: int) -> tuple[str, ChannelDetails] | None:
    channel = s.get(Channel, channel_id)
    if channel is None:
        return None
    title, source_key, ref = channel.title, channel.source_key, channel.url or channel.site_ref
    # No transaction stays open while the Source looks the channel up.
    s.rollback()
    return title, get_source(source_key).channel_details(ref)


def run_follow_channels(s: Session, *, channel_id: int | None = None) -> TaskResult:
    ids = [channel_id] if channel_id is not None else list(s.scalars(select(Channel.id).order_by(Channel.id)))
    s.rollback()
    found = added = 0
    failed: list[str] = []
    for one in ids:
        try:
            looked_up = _look_up(s, one)
        except Exception as exc:  # A Site that is down for one channel must not stop the others.
            logger.warning("Could not look at channel %s: %s", one, exc)
            failed.append(str(one))
            s.rollback()
            continue
        if looked_up is None:
            continue
        _title, details = looked_up

        def save(w: Session, channel_id: int = one, details: ChannelDetails = details):
            channel = w.get(Channel, channel_id)
            if channel is None:
                return None
            result = follow_channel(w, channel, details, now=datetime.now(timezone.utc))
            channel_sections_found(w, channel, result.asked)
            return result

        result = run_write_transaction(save)
        if result is not None:
            found += len(result.asked) + len(result.added) + len(result.ignored)
            added += len(result.added)
    summary = f"Looked at {len(ids) - len(failed)} {'channel' if len(ids) - len(failed) == 1 else 'channels'}"
    if found:
        summary += f", found {found} new {'section' if found == 1 else 'sections'} and added {added}"
    if failed:
        summary += f"; {len(failed)} could not be reached"
    return TaskResult(summary=summary, data={"channels": len(ids), "found": found, "added": added, "failed": failed})
