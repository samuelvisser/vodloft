from __future__ import annotations

from types import MappingProxyType

from ..contract import (
    MAIN_TAG, MIN_NEWEST_EPISODES, EpisodeMedia, EpisodePublishStatus, EpisodeTag, Feature, LinkKind, Playback,
    PublishStatusLabel, ResolvedLink, RssEpisodeType, SeasonRef, Site, Source, VideoDetails, publish_status_labels_with,
)
from .api.dw_api.client import ByShowSeason, MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .api.records import DwEpisodeRecord
from .auth import DeviceAuthClient
from .links import _access_token, _first, parse_link, resolve_link
from .playback import resolve_movie_playback

# Episode numbers .01 to .19 belong to an episode; .20 and up are the show's own extra content.
_SHOW_EXTRA_SEGMENT = 20


def _tag(record: DwEpisodeRecord) -> str:
    """The episode tag VODLoft gives the record, from its episode number and whether it is a trailer."""
    segment = record.ep_segment
    if record.ep_number is not None and 0 < segment < _SHOW_EXTRA_SEGMENT:
        return "ep-extra"
    if record.trailer:
        return "trailer"
    if record.ep_number is None or segment:
        return "aux"
    return MAIN_TAG


def _video(record: DwEpisodeRecord, season: SeasonRef | None) -> VideoDetails:
    return VideoDetails(
        slug=record.slug,
        url=record.sharing_url,
        title=record.title,
        description=record.description,
        duration=record.duration or None,
        image_url=_first(record.thumbnail_landscape_path, record.background_image_path),
        published_at=record.published_date,
        season=season,
        episode_number=record.ep_number,
        number_text=record.episode_number or None,
        tag=_tag(record),
    )


class DailyWireSource(Source):
    id = "dailywire"
    name = "The Daily Wire"
    domains = ("dailywire.com",)
    sites = (Site("dailywire", "The Daily Wire", domains, refresh_intervals="15m,30m,1h,3h,6h,24h,3d"),)
    kind_names = MappingProxyType({LinkKind.COLLECTION: "Show"})
    features = frozenset({
        Feature.COLLECTIONS,
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
    publish_status_labels = publish_status_labels_with(
        PublishStatusLabel(EpisodePublishStatus.SCHEDULED, "Scheduled", "The Daily Wire has scheduled the episode."),
        PublishStatusLabel(
            EpisodePublishStatus.DELAYED, "Officially delayed", "The Daily Wire has delayed the start of the episode.",
        ),
        PublishStatusLabel(
            EpisodePublishStatus.SOURCE_PROCESSING, "Processing at The Daily Wire",
            "The episode has ended, but The Daily Wire is still preparing the recording.",
        ),
        PublishStatusLabel(
            EpisodePublishStatus.PUBLISHED_PRELIMINARY, "Published (still contains countdown)",
            "Published, but the recording still opens with the countdown. VODLoft downloads it again once The Daily Wire removes it.",
        ),
    )

    def collection_ref(self, url: str) -> str | None:
        parsed = parse_link(url)
        return parsed[1] if parsed is not None and parsed[0] is LinkKind.COLLECTION else None

    def resolve(self, url: str) -> ResolvedLink | None:
        return resolve_link(url)

    def newest_episodes(self, url: str) -> list[VideoDetails]:
        """The episodes on the show's page, which lists its newest season's latest ones.
        When that page has fewer than a handful, the newest seasons' first pages fill them up."""
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.COLLECTION:
            raise ValueError("This is not a link to a show on The Daily Wire")
        client = MiddlewareClient(access_token=_access_token(), request_priority="interactive")
        show = client.get_show_page(slug=parsed[1])
        # The show page lists its seasons newest first.
        oldest_first = list(reversed(show.seasons))
        refs = {
            season.slug: SeasonRef(slug=season.slug, number=position, title=season.name)
            for position, season in enumerate(oldest_first, start=1)
        }
        found = [(record, show.latest_season.slug) for record in dict.fromkeys(show.latest_episodes)]
        for season in show.seasons:
            if len(found) >= MIN_NEWEST_EPISODES:
                break
            page = client.get_episodes_paginated(show.slug, ByShowSeason(season_dw_id=season.dw_id, page_size=50))
            known = {record.slug for record, _ in found}
            found += [(record, season.slug) for record in dict.fromkeys(page.items) if record.slug not in known]
        found.sort(key=lambda item: item[0].published_date, reverse=True)
        return [_video(record, refs.get(season_slug)) for record, season_slug in found]

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
