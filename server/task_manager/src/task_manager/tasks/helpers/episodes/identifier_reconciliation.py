from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from .events import queue_episode_identifier_changed_event
from .identifier import NumberedEpisode, refresh_episode_identifier

if TYPE_CHECKING:
    from backend.db.models import Episode


def reconcile_episode_identifier(
        s: Session,
        episode: "Episode",
        numbering: NumberedEpisode,
        *,
        previous_publish_status: str | None = None,
) -> bool:
    """Reconcile an identifier and publish its downstream-impact event when needed.

    This is the application-level reconciliation path. The lower-level identifier
    allocator owns only the identifier/counter mutation; this wrapper owns the
    system-wide consequence of changing a row that had already been published.
    """
    old_identifier = episode.episode_identifier
    changed = refresh_episode_identifier(s, episode, numbering)
    if changed:
        queue_episode_identifier_changed_event(
            s,
            episode=episode,
            old_episode_identifier=old_identifier,
            previous_publish_status=previous_publish_status,
        )
    return changed
