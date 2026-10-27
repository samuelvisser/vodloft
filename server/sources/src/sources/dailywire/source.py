from __future__ import annotations

from ..contract import MAIN_TAG, EpisodeMedia, EpisodeTag, Feature, Playback, ResolvedLink, RssEpisodeType, Source
from .api.dw_api.client import MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .auth import DeviceAuthClient
from .links import resolve_link
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
    episode_tags = (
        EpisodeTag(MAIN_TAG, "Episode", "A normal episode of the show", main=True),
        EpisodeTag(
            "ep-extra", "Ep. Extra", "Extra content for a specific episode", selected_by_default=False,
            rss_episode_type=RssEpisodeType.BONUS,
        ),
        EpisodeTag(
            "trailer", "Trailer", "A trailer for the show or its extra content", selected_by_default=False,
            rss_episode_type=RssEpisodeType.TRAILER,
        ),
        EpisodeTag("aux", "Auxiliary", "Extra content for the show", rss_episode_type=RssEpisodeType.BONUS),
    )

    def resolve(self, url: str) -> ResolvedLink | None:
        return resolve_link(url)

    def episode_media(self, *, slug: str, members_only: bool, interactive: bool = False) -> EpisodeMedia:
        client = MiddlewareClient(request_priority="interactive") if interactive else MiddlewareClient()
        detail = client.get_episode_details(slug, require_member_exclusive=members_only)
        return EpisodeMedia(video_url=detail.video_url, audio_url=detail.audio_url)

    def movie_playback(
        self, *, movie_slug: str, title: str, duration: float | None,
        extra_slug: str | None = None, is_extra: bool = False, is_official_trailer: bool = False,
    ) -> Playback:
        tokens = DeviceAuthClient().get_token()
        client = MovieMiddlewareClient(access_token=tokens.access_token if tokens else None)
        selection = resolve_movie_playback(
            client, movie_slug=movie_slug, title=title, duration=duration,
            is_extra=is_extra, extra_slug=extra_slug, is_official_trailer=is_official_trailer,
        )
        return Playback(url=selection.url, metadata=selection.metadata)
