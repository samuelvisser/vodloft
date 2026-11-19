from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.db.datetime_types import utc_datetime
from backend.db.models import Episode
from backend.services.site_settings import site_setting
from backend.services.sites import episode_site_key
from backend.types.episode_types import EpisodePublishStatus
from backend.utils.episode_publication_timing import best_effort_published_date
from config import get_settings
from config.settings.site_settings import SiteSetting


def episode_download_delay_ready_at(episode: Episode) -> datetime | None:
    """Return when the post-publication download delay of the episode's Site expires."""
    settings = get_settings().download_settings
    delay_minutes = site_setting(episode_site_key(episode), SiteSetting.DOWNLOAD_DELAY_MINUTES)
    if delay_minutes <= 0:
        return None

    publication_time: datetime | None
    if episode.publish_status == EpisodePublishStatus.PUBLISHED_FINAL:
        if settings.ensure_safe_delay:
            publication_time = (
                episode.safe_published_final
                or episode.recorded_published_final
            )
            if publication_time is None:
                # For episodes added during an initial index
                publication_time = best_effort_published_date(episode)
        else:
            publication_time = best_effort_published_date(episode)
    elif episode.publish_status == EpisodePublishStatus.PUBLISHED_PRELIMINARY:
        publication_time = episode.safe_live_ended
        if publication_time is None and episode.published_date is not None:
            publication_time = utc_datetime(episode.published_date)
    else:
        publication_time = None

    if publication_time is None:
        return None
    return utc_datetime(publication_time) + timedelta(minutes=delay_minutes)


def episode_download_delay_passed(
        episode: Episode,
        *,
        now: datetime | None = None,
) -> bool:
    """Return whether the configured post-publication download delay has elapsed."""
    ready_at = episode_download_delay_ready_at(episode)
    if ready_at is None:
        return True
    current = utc_datetime(now or datetime.now(timezone.utc))
    return ready_at <= current
