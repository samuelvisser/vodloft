from __future__ import annotations

import logging
import re
from email.utils import format_datetime
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import Request
from sqlalchemy.orm import Session

from backend.services.sites import collection_site
from backend.services.thumbnails import is_own_thumbnail
from backend.api.models.rss_stream_profile import RssStreamProfileAPIRead
from backend.db.datetime_types import utc_datetime
from backend.db.models import Episode, RssStreamProfile
from backend.db.models.media_download import EpisodeMediaDownload
from backend.services.stream_episodes import download_kind, get_stream_items
from backend.types.download_profile_types import EpIdType
from backend.types.episode_types import EpisodeExtraType, EpisodePublishStatus
from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, PreferredFormat
from backend.types.collection_types import EpisodeIdentifier, EpisodeOrder
from backend.types.stream_profile_types import (
    RSS_AUDIO_PRIMARY_OUTPUT_MODES,
    RSS_HLS_OUTPUT_MODES,
    RSS_MP4_OUTPUT_MODES,
    RssVideoOutputMode,
)
from backend.utils.feed_urls import request_base_url
from backend.services.video_cache import get_cached_mp4_size, joined_key, joins_mp4, stream_height
from .source_stream import estimated_audio_size, estimated_video_size
from .source_tracks import NEWEST_EPISODES_JOINED_AHEAD, EpisodeRef, join_in_background
from backend.services.collection_cookies import uses_cookies
from sources import EpisodeTag, Feature, UnknownSourceError, get_source


logger = logging.getLogger(__name__)

_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_PODCAST_NS = "https://podcastindex.org/namespace/1.0"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_HLS_MIME_TYPE = "application/x-mpegURL"
_BARE_HTML_AMPERSAND_RE = re.compile(
    r"&(?!(?:#\d+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);)"
)


def _sub_text(parent: Element, tag: str, text: Optional[str]) -> Element:
    element = SubElement(parent, tag)
    element.text = text
    return element


def _escape_bare_html_ampersands(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return _BARE_HTML_AMPERSAND_RE.sub("&amp;", text)


def _append_episode_number_values(
    item: Element,
    *,
    episode_number: int,
    podcast_episode_number: str | None = None,
) -> None:
    if episode_number < 1:
        return
    _sub_text(item, "itunes:episode", str(episode_number))
    _sub_text(
        item,
        "podcast:episode",
        podcast_episode_number or str(episode_number),
    )


def _append_identifier_episode_number(item: Element, episode: Episode) -> None:
    info = episode.episode_identifier_info
    if (
        info.type not in {EpIdType.EP, EpIdType.EP_EXTRA}
        or info.episode_number is None
        or not info.episode_number.isdigit()
    ):
        return

    episode_number = int(info.episode_number)
    podcast_episode_number = str(episode_number)
    if info.sub_episode_number and info.sub_episode_number.isdigit():
        sub_episode_number = int(info.sub_episode_number)
        if sub_episode_number > 0:
            podcast_episode_number = f"{episode_number}.{sub_episode_number}"

    _append_episode_number_values(
        item,
        episode_number=episode_number,
        podcast_episode_number=podcast_episode_number,
    )


def _episode_tag(episode: Episode, key: str | None) -> EpisodeTag | None:
    """The tag the episode's Source declares for it, such as a YouTube Short."""
    try:
        return get_source(episode.source_key).episode_tag(key)
    except UnknownSourceError:
        return None


def _append_podcast_item_metadata(
        item: Element,
        episode: Episode,
        *,
        identifier_type: str,
) -> None:
    info = episode.episode_identifier_info

    if (
        info.type == EpIdType.TRAILER
        or (
            info.type == EpIdType.EP_EXTRA
            and info.extra_type == EpisodeExtraType.TRAILER
        )
    ):
        episode_type = "trailer"
    elif info.type in {EpIdType.AUX, EpIdType.EP_EXTRA}:
        episode_type = "bonus"
    elif info.type != EpIdType.EP and (tag := _episode_tag(episode, info.type)) is not None:
        episode_type = tag.rss_episode_type.value
    else:
        episode_type = "full"
    _sub_text(item, "itunes:episodeType", episode_type)

    if identifier_type == EpisodeIdentifier.NUMBERED.value:
        # Numbered identifiers represent a real collection-global episode number.
        # Standalone AUX/TRAILER counters are intentionally excluded above.
        if info.season_number is None:
            _append_identifier_episode_number(item, episode)
        return

    if identifier_type != EpisodeIdentifier.SEASONAL.value:
        return

    season = episode.season
    if season is None or season.season_number < 1:
        return

    season_number = int(season.season_number)
    _sub_text(item, "itunes:season", str(season_number))

    podcast_season = SubElement(
        item,
        "podcast:season",
        {"name": season.name},
    )
    podcast_season.text = str(season_number)

    # Only source-backed seasonal identifiers have a real episode number.
    # Standalone auxiliary/trailer counters are collection-global VODLoft identifiers
    # and must not be exposed as season episode numbers.
    if info.season_number != season_number:
        return

    _append_identifier_episode_number(item, episode)


def _append_alternate_enclosure(
        item: Element,
        *,
        media_type: str,
        media_url: str,
        title: str,
        length: int = 0,
) -> None:
    alternate = SubElement(
        item,
        "podcast:alternateEnclosure",
        {
            "type": media_type,
            "length": str(length),
            "lang": "en",
            "title": title,
            "rel": "alternate",
        },
    )
    SubElement(alternate, "podcast:source", {"uri": media_url})


def _mp4_size(
        episode: Episode,
        download: Optional[EpisodeMediaDownload],
        *,
        joined_height: Optional[int],
        video_height: Optional[int],
) -> Optional[int]:
    """The size a feed gives an episode's MP4 video: the file's own when it is downloaded or in the RSS
    cache, and otherwise an estimate. An app may pass over a video that says it is empty."""
    if download is not None and download_kind(download) == "mp4" and download.artifact_size_bytes:
        return download.artifact_size_bytes
    cached = get_cached_mp4_size(joined_key(episode.uuid, joined_height) if joined_height else episode.uuid)
    return cached or estimated_video_size(episode.duration, video_height)


def _append_item(
        channel: Element,
        *,
        media_base_url: str,
        episode: Episode,
        profile: RssStreamProfile,
        download: Optional[EpisodeMediaDownload] = None,
        joined_height: Optional[int] = None,
        video_height: Optional[int] = None,
) -> None:
    item = SubElement(channel, "item")
    _sub_text(item, "title", episode.title)

    guid = SubElement(item, "guid", {"isPermaLink": "false"})
    guid.text = episode.uuid

    if episode.description:
        _sub_text(
            item,
            "description",
            _escape_bare_html_ampersands(episode.description),
        )

    pub_date = (
        episode.published_date
        or episode.went_live_date
        or episode.created_at
    )
    if pub_date is not None:
        _sub_text(item, "pubDate", format_datetime(utc_datetime(pub_date)))

    media_url = f"{media_base_url}/episodes/{episode.slug}"
    audio_url = f"{media_url}/audio.m4a"
    mp4_url = f"{media_url}/video.mp4"
    hls_url = f"{media_url}/video.m3u8"

    if profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value:
        enclosure_url = audio_url
        enclosure_type = "audio/mp4"
    elif profile.video_output_mode in RSS_AUDIO_PRIMARY_OUTPUT_MODES:
        enclosure_url = audio_url
        enclosure_type = "audio/mp4"
    else:
        enclosure_url = mp4_url
        enclosure_type = "video/mp4"
    # Apps show the length as the episode's size: a downloaded file's own size, and otherwise an estimate,
    # which for audio is at 128 kbit/s, as streamed audio has.
    mp4_size = None
    if (
        profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value
        and profile.video_output_mode in RSS_MP4_OUTPUT_MODES
    ):
        mp4_size = _mp4_size(episode, download, joined_height=joined_height, video_height=video_height)
    if enclosure_url != audio_url:
        estimated_size = mp4_size
    elif download is not None and download_kind(download) == "audio" and download.artifact_size_bytes:
        estimated_size = download.artifact_size_bytes
    else:
        estimated_size = estimated_audio_size(episode.duration)

    SubElement(
        item,
        "enclosure",
        {
            "url": enclosure_url,
            "length": str(estimated_size or 0),
            "type": enclosure_type,
        },
    )
    _sub_text(item, "link", media_url)

    _append_podcast_item_metadata(
        item,
        episode,
        identifier_type=profile.collection.episode_identifier,
    )

    if profile.preferred_format != PreferredFormat.FORMAT_AUDIO_ONLY.value:
        mode = profile.video_output_mode
        if mode == RssVideoOutputMode.AUDIO_MP4.value:
            _append_alternate_enclosure(
                item,
                media_type="video/mp4",
                media_url=mp4_url,
                title="Video",
                length=mp4_size or 0,
            )
        elif mode in RSS_HLS_OUTPUT_MODES:
            _append_alternate_enclosure(
                item,
                media_type=_HLS_MIME_TYPE,
                media_url=hls_url,
                title="Adaptive Video",
            )

    _sub_text(
        item,
        "itunes:duration",
        str(int(round(episode.duration))) if episode.duration else "0",
    )

    image_url = (
        episode.thumbnail_square_path
        or episode.thumbnail_landscape_path
        or episode.thumbnail_portrait_path
    )
    # A thumbnail VODLoft made needs a signed-in browser, which a podcast app is not.
    if image_url and not is_own_thumbnail(image_url):
        SubElement(item, "itunes:image", {"href": image_url})


def _joined_mp4_height(profile: RssStreamProfile) -> Optional[int]:
    """The resolution a feed's MP4 video is joined at from its Site's tracks, when it serves MP4 video
    that is not downloaded at a resolution the Site has no MP4 file with sound of."""
    if (
        not profile.use_source_stream
        or profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
        or profile.video_output_mode not in RSS_MP4_OUTPUT_MODES
    ):
        return None
    site = collection_site(profile.collection)
    height = stream_height(site, PREFERRED_FORMAT_HEIGHTS.get(profile.preferred_format))
    return height if joins_mp4(site, height) else None


def _join_newest_ahead(
        profile: RssStreamProfile, items: list[tuple[Episode, Optional[EpisodeMediaDownload]]], height: int,
) -> None:
    """Start joining the MP4 files of the feed's newest episodes that are not downloaded as MP4, so
    they are ready before anyone plays them."""
    try:
        source = get_source(profile.collection.source_key)
    except UnknownSourceError:
        return
    if not source.has(Feature.PAGE_STREAMS):
        return
    use_cookies = uses_cookies(profile.collection)
    waiting = [
        episode for episode, download in items
        if (download is None or download_kind(download) != "mp4")
        and episode.publish_status != EpisodePublishStatus.LIVE.value
    ]
    for episode in waiting[:NEWEST_EPISODES_JOINED_AHEAD]:
        join_in_background(source, EpisodeRef(episode.uuid, episode.sharing_url, use_cookies), height)


def render_rss_feed(
        s: Session,
        request: Request,
        profile: RssStreamProfile,
) -> bytes:
    collection = profile.collection
    effective_title = RssStreamProfileAPIRead.model_validate(profile).effective_title
    items = get_stream_items(s, profile)

    media_base_url = f"{request_base_url(request)}/feeds/rss/{profile.token}"

    rss = Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:itunes": _ITUNES_NS,
            "xmlns:podcast": _PODCAST_NS,
            "xmlns:atom": _ATOM_NS,
        },
    )
    channel = SubElement(rss, "channel")
    _sub_text(channel, "title", effective_title)
    _sub_text(channel, "link", collection.sharing_url)
    _sub_text(
        channel,
        "description",
        _escape_bare_html_ampersands(collection.description or effective_title),
    )
    _sub_text(channel, "language", "en-us")
    _sub_text(channel, "generator", "VODLoft")
    _sub_text(channel, "itunes:author", collection.author_name)
    _sub_text(channel, "itunes:explicit", "false")
    # The items stay newest first, as feeds list them; itunes:type tells podcast apps which way to show
    # them, and a serial show's episodes by season.
    _sub_text(
        channel,
        "itunes:type",
        (
            "episodic"
            if collection.episode_order == EpisodeOrder.NEWEST_FIRST.value
            else "serial"
        ),
    )
    SubElement(
        channel,
        "atom:link",
        {
            "href": profile.feed_url,
            "rel": "self",
            "type": "application/rss+xml",
        },
    )
    _sub_text(
        channel,
        "podcast:medium",
        "podcast"
        if profile.preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value
        else "video",
    )

    image_url = (
        collection.thumbnail_square_path
        or collection.thumbnail_landscape_path
        or collection.logo_image_path
    )
    if image_url:
        SubElement(channel, "itunes:image", {"href": image_url})
        image = SubElement(channel, "image")
        _sub_text(image, "url", image_url)
        _sub_text(image, "title", effective_title)
        _sub_text(image, "link", collection.sharing_url)

    joined_height = _joined_mp4_height(profile)
    preferred_height = PREFERRED_FORMAT_HEIGHTS.get(profile.preferred_format)
    video_height = stream_height(collection_site(collection), preferred_height) or preferred_height
    if joined_height is not None:
        _join_newest_ahead(profile, items, joined_height)
    for episode, download in items:
        _append_item(
            channel,
            media_base_url=media_base_url,
            episode=episode,
            profile=profile,
            download=download,
            joined_height=joined_height,
            video_height=video_height,
        )

    return tostring(rss, encoding="UTF-8", xml_declaration=True)
