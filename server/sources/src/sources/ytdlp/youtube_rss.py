"""YouTube's RSS feeds, which list a channel's or playlist's 15 newest videos without a key."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

import requests

from ..contract import MAIN_TAG, VideoDetails

FEED_URL = "https://www.youtube.com/feeds/videos.xml"
_TIMEOUT_SECONDS = 20
_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


class FeedError(RuntimeError):
    pass


def _feed(channel_id: str | None, playlist_id: str | None) -> ET.Element:
    params = {"channel_id": channel_id} if channel_id else {"playlist_id": playlist_id}
    try:
        response = requests.get(FEED_URL, params=params, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise FeedError(f"Could not read the YouTube feed: {exc}") from exc
    if not response.ok:
        raise FeedError(f"The YouTube feed answered HTTP {response.status_code}")
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise FeedError(f"The YouTube feed is not valid XML: {exc}") from exc


def latest_video_ids(*, channel_id: str | None = None, playlist_id: str | None = None) -> list[str]:
    """The feed's video IDs, newest first."""
    root = _feed(channel_id, playlist_id)
    return [
        element.text for element in root.findall("atom:entry/yt:videoId", _NAMESPACES) if element.text
    ]


def _text(entry: ET.Element, path: str) -> str | None:
    element = entry.find(path, _NAMESPACES)
    return element.text if element is not None and element.text else None


def _attribute(entry: ET.Element, path: str, name: str) -> str | None:
    element = entry.find(path, _NAMESPACES)
    return element.get(name) or None if element is not None else None


def _published(entry: ET.Element) -> datetime | None:
    value = _text(entry, "atom:published")
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def latest_videos(*, channel_id: str | None = None, playlist_id: str | None = None) -> list[VideoDetails]:
    """The feed's videos, newest first, as far as the feed describes them: it gives no duration."""
    videos = []
    for entry in _feed(channel_id, playlist_id).findall("atom:entry", _NAMESPACES):
        video_id = _text(entry, "yt:videoId")
        if not video_id:
            continue
        link = _attribute(entry, "atom:link", "href") or f"https://www.youtube.com/watch?v={video_id}"
        videos.append(VideoDetails(
            slug=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=_text(entry, "atom:title") or video_id,
            description=_text(entry, "media:group/media:description"),
            image_url=_attribute(entry, "media:group/media:thumbnail", "url"),
            author_name=_text(entry, "atom:author/atom:name"),
            author_url=_text(entry, "atom:author/atom:uri"),
            published_at=_published(entry),
            # The feed links a Short to its Shorts page; it cannot tell a livestream from a video.
            tag="short" if "/shorts/" in link else MAIN_TAG,
        ))
    return videos
