from __future__ import annotations

from ..contract import EpisodeMedia, Feature, MoviePlayback, Source
from .api.dw_api.client import MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .auth import DeviceAuthClient
from .playback import resolve_movie_playback


class DailyWireSource(Source):
    id = "dailywire"
    name = "The Daily Wire"
    domains = ("dailywire.com",)
    features = frozenset({
        Feature.SHOWS,
        Feature.MOVIES,
        Feature.MOVIE_EXTRAS,
        Feature.BROWSE,
        Feature.LOGIN,
        Feature.LIVE_EPISODES,
        Feature.MEMBERSHIP_LEVELS,
        Feature.RSS_STREAMING,
    })

    def episode_media(self, *, slug: str, members_only: bool, interactive: bool = False) -> EpisodeMedia:
        client = MiddlewareClient(request_priority="interactive") if interactive else MiddlewareClient()
        detail = client.get_episode_details(slug, require_member_exclusive=members_only)
        return EpisodeMedia(video_url=detail.video_url, audio_url=detail.audio_url)

    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> MoviePlayback:
        tokens = DeviceAuthClient().get_token()
        client = MovieMiddlewareClient(access_token=tokens.access_token if tokens else None)
        selection = resolve_movie_playback(
            client, movie_slug=movie_slug, title=title, duration=duration,
            is_extra=is_extra, extra_slug=extra_slug, is_official_trailer=is_official_trailer,
        )
        return MoviePlayback(url=selection.url, metadata=selection.metadata)
