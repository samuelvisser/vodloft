from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.services.episode_numbering import CountedNumbers, Numbering, follows_facts, identify
from backend.services.sites import collection_site
from backend.types.collection_types import EpisodeIdentifier
from backend.types.download_profile_types import EpIdType
from .events import queue_episode_identifier_changed_event

if TYPE_CHECKING:
    from backend.db.models import Episode

logger = logging.getLogger(__name__)


def _kind(identifier: str) -> str:
    return identifier.partition(".")[0]


def reconcile_episode_identifier(
        s: Session,
        episode: "Episode",
        numbering: Numbering,
        *,
        previous_publish_status: str | None = None,
) -> bool:
    """Give one episode the identifier what its Source says about it now calls for, such as a new publication date
    for a date-based collection or a new episode number from The Daily Wire, and tell what depends on it. An
    identifier VODLoft counted, such as a trailer's or a numbered collection's own number, stays as long as the
    episode is still of that kind. Returns whether it changed."""
    from backend.db.models import Episode

    if episode.part_of is not None or episode.season is None:
        return False
    collection = episode.collection
    identification = EpisodeIdentifier(collection.episode_identifier)
    site = collection_site(collection)
    old_identifier = episode.episode_identifier
    taken = set(s.scalars(select(Episode.episode_identifier).where(
        Episode.collection_id == collection.id, Episode.id != episode.id,
    )))
    desired = identify(identification, site, episode.season, numbering, set(taken), CountedNumbers(taken))
    if desired == old_identifier:
        return False
    if not follows_facts(identification, site, numbering) and _kind(desired) == _kind(old_identifier):
        return False
    if _kind(desired) == EpIdType.AUX and _kind(old_identifier) == EpIdType.AUX:
        # The Source's place for it is taken by another episode, so it stays the auxiliary one it is.
        return False
    episode.episode_identifier = desired
    s.flush()
    logger.info("Episode %s is now %s instead of %s, from its Source's details", episode.id, desired, old_identifier)
    queue_episode_identifier_changed_event(
        s,
        episode=episode,
        old_episode_identifier=old_identifier,
        previous_publish_status=previous_publish_status,
    )
    return True
