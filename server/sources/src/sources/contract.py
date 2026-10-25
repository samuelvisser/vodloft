"""The contract every Source implements.

The rest of VODLoft talks to a service only through these types, never through
a Source's own client, records or errors. The contract only holds what has a
caller today; methods are added together with the feature that needs them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar
from urllib.parse import urlsplit


class Feature(StrEnum):
    """Optional capabilities. Code that only makes sense for some services
    checks the feature instead of the Source id."""

    SHOWS = "shows"
    MOVIES = "movies"
    MOVIE_EXTRAS = "movie_extras"
    BROWSE = "browse"
    LOGIN = "login"
    LIVE_EPISODES = "live_episodes"
    MEMBERSHIP_LEVELS = "membership_levels"
    RSS_STREAMING = "rss_streaming"


@dataclass(frozen=True)
class EpisodeMedia:
    """Where the current media of an episode can be fetched from."""

    video_url: str | None
    audio_url: str | None
    drm_protected: bool = False


@dataclass(frozen=True)
class MoviePlayback:
    """The playable URL of a movie or movie extra.

    ``metadata`` is the Source's own record when the playback lookup also
    returned fresher metadata; the Source that produced it knows how to apply it.
    """

    url: str
    metadata: Any = None
    drm_protected: bool = False


class Source(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    domains: ClassVar[tuple[str, ...]]
    features: ClassVar[frozenset[Feature]]

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def handles(self, url: str) -> bool:
        """True when the link's host is one of this Source's domains or a subdomain of one."""
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)

    @abstractmethod
    def episode_media(
        self, *, slug: str, members_only: bool, interactive: bool = False,
    ) -> EpisodeMedia:
        """Look up the current media URLs of an episode."""

    @abstractmethod
    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> MoviePlayback:
        """Resolve the playable URL of a movie or one of its extras."""
