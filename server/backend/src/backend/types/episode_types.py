from enum import StrEnum

from sources.contract import EpisodePublishStatus

__all__ = [
    "EpisodeExtraType", "EpisodePublishStatus", "PENDING_EPISODE_PUBLISH_STATUSES",
    "POST_LIVE_EPISODE_PUBLISH_STATUSES", "PRE_PUBLISH_EPISODE_PUBLISH_STATUSES",
]


class EpisodeExtraType(StrEnum):
    OTHER = "other"
    TRAILER = "trailer"


PENDING_EPISODE_PUBLISH_STATUSES = frozenset({
    EpisodePublishStatus.SCHEDULED,
    EpisodePublishStatus.DELAYED,
    EpisodePublishStatus.LIVE,
    EpisodePublishStatus.SOURCE_PROCESSING,
    EpisodePublishStatus.PUBLISHED_PRELIMINARY,
})

POST_LIVE_EPISODE_PUBLISH_STATUSES = frozenset({
    EpisodePublishStatus.SOURCE_PROCESSING,
    EpisodePublishStatus.PUBLISHED_PRELIMINARY,
    EpisodePublishStatus.PUBLISHED_FINAL,
})

PRE_PUBLISH_EPISODE_PUBLISH_STATUSES = frozenset({
    EpisodePublishStatus.SCHEDULED,
    EpisodePublishStatus.DELAYED,
    EpisodePublishStatus.LIVE,
})