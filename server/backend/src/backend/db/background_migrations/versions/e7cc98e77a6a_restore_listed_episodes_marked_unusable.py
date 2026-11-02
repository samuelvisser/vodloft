"""Restore listed episodes that a metadata refresh marked as having no usable media.

"Refresh metadata" looked every episode up at The Daily Wire, also the episodes
of yt-dlp and NPO Start Collections. The Daily Wire does not know those, so each
one came back "not found" and was marked as having no usable media, with a
``not-usable.N`` identifier in place of its own. Only Daily Wire episodes can
lose their media that way, so every other episode in that state gets its own
identifier back and is published again. Its downloaded files were never touched.

Revision ID: e7cc98e77a6a
Revises: 4e8a2c7f1d95
"""

from __future__ import annotations

from sqlalchemy import select

from backend.db.core import get_session
from backend.db.models import Collection, Episode
from backend.types.episode_types import EpisodePublishStatus


revision = "e7cc98e77a6a"
down_revision = "4e8a2c7f1d95"
title = "Restore yt-dlp and NPO Start episodes marked as having no usable media"

_DAILYWIRE = "dailywire"
_PREVIOUS_IDENTIFIER = "no_usable_media.previous_identifier"
_INCIDENT_KEYS = {"no_usable_media.reason", "no_usable_media.since", _PREVIOUS_IDENTIFIER}
_NOT_USABLE_COUNTER = "ep_id.latest_not_usable_num"


def _restore(session) -> int:
    episodes = list(session.scalars(
        select(Episode).where(
            Episode.source_key != _DAILYWIRE,
            Episode.publish_status == EpisodePublishStatus.NO_USABLE_MEDIA.value,
        ).order_by(Episode.id)
    ))
    restored = 0
    collection_ids: set[int] = set()
    for episode in episodes:
        previous = episode.get_meta(_PREVIOUS_IDENTIFIER)
        if previous:
            taken = session.scalar(
                select(Episode.id).where(
                    Episode.collection_id == episode.collection_id,
                    Episode.id != episode.id,
                    Episode.episode_identifier == previous,
                ).limit(1)
            )
            if taken is not None:
                # Another episode has its identifier now; leave this one for the user to look at.
                continue
            episode.episode_identifier = previous
            session.flush()
        episode.publish_status = EpisodePublishStatus.PUBLISHED_FINAL.value
        episode.metadata_is_final = True
        for item in list(episode.meta_items):
            if item.key in _INCIDENT_KEYS:
                episode.meta_items.remove(item)
        collection_ids.add(episode.collection_id)
        restored += 1
    session.flush()

    for collection_id in collection_ids:
        still_quarantined = session.scalar(
            select(Episode.id).where(
                Episode.collection_id == collection_id,
                Episode.episode_identifier.startswith("not-usable."),
            ).limit(1)
        )
        collection = session.get(Collection, collection_id)
        if still_quarantined is None and collection is not None:
            for item in list(collection.meta_items):
                if item.key == _NOT_USABLE_COUNTER:
                    collection.meta_items.remove(item)
    return restored


async def migrate(context) -> None:
    context.update_progress(0, 1, "Restoring episodes wrongly marked as having no usable media")
    session = get_session()
    try:
        _restore(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    context.update_progress(1, 1, "Restoring episodes wrongly marked as having no usable media")
