from __future__ import annotations

from datetime import datetime

from backend.db.datetime_types import utc_datetime
from backend.db.models import Episode
from backend.types.episode_types import EpisodePublishStatus
from backend.services.metadata_refresh import refresh_watch_expired, site_refresh_offsets
from sources.dailywire.api.records import DwEpisodeDetailRecord


METADATA_REFRESH_REQUESTED_EVENT = "episode.metadata_refresh_requested"


def ensure_utc(value: datetime) -> datetime:
    """Normalize one timezone-aware instant to UTC.

    Runtime episode lifecycle data must never infer an offset for a naive value.
    Legacy SQLite rows are normalized by ``UTCDateTime`` when they are read.
    """
    return utc_datetime(value)


def episode_refresh_offsets(episode: Episode) -> tuple[int, ...]:
    """The refresh schedule of the episode's Site, in seconds after publication."""
    collection = episode.collection
    return site_refresh_offsets(collection.site if collection is not None else None)


def metadata_is_final_for_new_episode(
        publish_status: str | EpisodePublishStatus,
        published_date: datetime | None,
        offsets: tuple[int, ...],
        *,
        now: datetime | None = None,
) -> bool:
    """Choose the initial persistent metadata-finality state for a new episode."""
    status = (
        publish_status.value
        if isinstance(publish_status, EpisodePublishStatus)
        else str(publish_status)
    )
    if status != EpisodePublishStatus.PUBLISHED_FINAL.value:
        return False
    return refresh_watch_expired(published_date, offsets, now=now)


def update_episode_from_dailywire(
        episode: Episode,
        dw_episode: DwEpisodeDetailRecord,
) -> None:
    """Refresh Daily Wire metadata without changing VODLoft-owned lifecycle state."""
    protected_fields = {
        "id",
        "collection_id",
        "season_id",
        "index",
        "episode_identifier",
        "publish_status",
        "metadata_is_final",
    }
    model_fields = set(Episode.__mapper__.attrs.keys())
    for field, value in dw_episode.model_dump(mode="python", by_alias=False).items():
        if field in model_fields and field not in protected_fields:
            setattr(episode, field, value)
    episode.dw_episode_number = dw_episode.episode_number or None
