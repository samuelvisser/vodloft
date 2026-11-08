from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

import requests

from downloader.hls import is_master_playlist, media_playlist_segments, parse_master_playlist

from ..contract import (
    Access, MAIN_TAG, MIN_NEWEST_EPISODES, EpisodeMedia, EpisodePublishStatus, EpisodeTag, Feature, LinkKind, Playback,
    DownloadOptions, PublishStatusLabel, ResolvedLink, RssEpisodeType, SeasonRef, Site, SiteSetting, SiteSettings, Source, StreamMethod,
    UpgradeChecks, UpgradeImprovement, UpgradeOffer, VideoDetails, publish_status_labels_with,
)
from .api.dw_api.client import ByShowSeason, MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .api.records import DwEpisodeRecord
from .api.types.user_info import DwMembershipLevel
from .api.utils.validators.available_for_list import parse_tiers
from .auth import DeviceAuthClient
from .auth.storage import TokenStore
from .links import _access_token, _first, parse_link, resolve_link
from .playback import resolve_movie_playback

_PLAYLIST_TIMEOUT_SECONDS = 15

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


# The Daily Wire's paid membership levels, cheapest first. Their keys are The Daily Wire's own names.
MEMBERSHIP_ACCESSES = tuple(
    Access(level.value, label, f"Only Daily Wire {label} members can watch this.")
    for level, label in (
        (DwMembershipLevel.INSIDER, "Insider"),
        (DwMembershipLevel.INSIDER_PLUS, "Insider Plus"),
        (DwMembershipLevel.ALL_ACCESS, "All Access"),
    )
)


def episode_access(available_for: Sequence[object]) -> str | None:
    """The cheapest membership level an episode is available for, or None when anyone can watch it."""
    if DwMembershipLevel.FREE in available_for:
        return None
    return next((access.key for access in MEMBERSHIP_ACCESSES if DwMembershipLevel(access.key) in available_for), None)


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
        access=episode_access(record.available_for),
    )


_VIDEO_HEIGHTS = (480, 720, 1080)


class DailyWireSource(Source):
    id = "dailywire"
    name = "The Daily Wire"
    domains = ("dailywire.com",)
    sites = (Site(
        "dailywire", "The Daily Wire", domains,
        stream_methods=frozenset({StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE}),
        stream_video_heights=_VIDEO_HEIGHTS,
        # Fixed versions: an HLS stream of 480p, 720p and 1080p, and audio.
        downloads=DownloadOptions(video_heights=_VIDEO_HEIGHTS, hls_bundle=True, quality_choices=False),
        # The Daily Wire sometimes edits an episode after it is out, such as cutting a long live stream down.
        upgrade_checks=UpgradeChecks((UpgradeImprovement.LENGTH,)),
        settings=SiteSettings(
            # It publishes live episodes with a countdown in the recording at first, so a Download Profile can
            # download them with the countdown and again once the final version is out.
            shows=frozenset({SiteSetting.DOWNLOAD_WITH_COUNTDOWN}),
            # It makes no subtitles of its own.
            hides=frozenset({SiteSetting.AUTO_SUBTITLES}),
            presets=MappingProxyType({
                SiteSetting.METADATA_REFRESH: "15m,30m,1h,3h,6h,24h,3d",
                SiteSetting.DOWNLOAD_WITH_COUNTDOWN: False,
                SiteSetting.UPGRADE_CHECK: True,
                SiteSetting.UPGRADE_AFTER_DAYS: 3,
                SiteSetting.UPGRADE_IMPROVEMENTS: [UpgradeImprovement.LENGTH.value],
            }),
        ),
        accesses=MEMBERSHIP_ACCESSES,
    ),)
    kind_names = MappingProxyType({LinkKind.COLLECTION: "Show"})
    features = frozenset({
        Feature.COLLECTIONS,
        Feature.MOVIES,
        Feature.MOVIE_EXTRAS,
        Feature.BROWSE,
        Feature.LOGIN,
        Feature.LIVE_EPISODES,
        Feature.MEMBERSHIP_LEVELS,
        Feature.EPISODE_LOOKUPS,
        Feature.OWN_STUDIO,
    })
    episode_tags = (
        EpisodeTag(MAIN_TAG, "Episode", "A normal episode of the show", "episode", "episodes", main=True),
        EpisodeTag(
            "ep-extra", "Ep. Extra", "Extra content for a specific episode", "episode extra", "episode extras", selected_by_default=False,
            rss_episode_type=RssEpisodeType.BONUS,
        ),
        EpisodeTag(
            "trailer", "Trailer", "A trailer for the show or its extra content", "trailer", "trailers", selected_by_default=False,
            rss_episode_type=RssEpisodeType.TRAILER,
        ),
        EpisodeTag("aux", "Auxiliary", "Extra content for the show", "auxiliary episode", "auxiliary episodes", rss_episode_type=RssEpisodeType.BONUS),
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

    def current_access(self, *, slug: str, url: str) -> str | None:
        payload = MiddlewareClient().get_episode_payload(slug)
        return episode_access(parse_tiers(payload.get("availableFor")))

    def upgrade_offer(self, url: str, *, sponsorblock_categories: Sequence[str] = ()) -> UpgradeOffer:
        """The length of the episode's stream as The Daily Wire serves it now. The listed runtime is
        only a hint, so the playlist itself is measured."""
        parsed = parse_link(url)
        if parsed is None or parsed[0] is not LinkKind.EPISODE:
            raise ValueError("This is not a link to an episode on The Daily Wire")
        detail = MiddlewareClient().get_episode_details(
            parsed[1], require_member_exclusive=DeviceAuthClient().get_token() is not None,
        )
        return UpgradeOffer(duration=_stream_length(detail.video_url) if detail.video_url else None)

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

    def import_sign_in(self, records: Mapping[str, str]) -> None:
        store = TokenStore()
        for store_key, record in records.items():
            store.store_record(store_key, str(record))


def _playlist(url: str) -> tuple[str, str]:
    response = requests.get(url, timeout=_PLAYLIST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text, response.url


def _stream_length(url: str) -> float | None:
    """The length of an HLS stream in seconds: its first rendition's segments added up. Every
    rendition of a stream is equally long."""
    text, url = _playlist(url)
    if is_master_playlist(text):
        renditions = parse_master_playlist(text, url)
        if not renditions:
            return None
        text, url = _playlist(renditions[0].url)
    segments = media_playlist_segments(text, url)
    return sum(segment.duration for segment in segments) if segments else None
