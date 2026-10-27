"""YouTube's RSS feeds, which list a channel's or playlist's 15 newest videos without a key."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

FEED_URL = "https://www.youtube.com/feeds/videos.xml"
_TIMEOUT_SECONDS = 20
_NAMESPACES = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


class FeedError(RuntimeError):
    pass


def latest_video_ids(*, channel_id: str | None = None, playlist_id: str | None = None) -> list[str]:
    """The feed's video IDs, newest first."""
    params = {"channel_id": channel_id} if channel_id else {"playlist_id": playlist_id}
    try:
        response = requests.get(FEED_URL, params=params, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise FeedError(f"Could not read the YouTube feed: {exc}") from exc
    if not response.ok:
        raise FeedError(f"The YouTube feed answered HTTP {response.status_code}")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise FeedError(f"The YouTube feed is not valid XML: {exc}") from exc
    return [
        element.text for element in root.findall("atom:entry/yt:videoId", _NAMESPACES) if element.text
    ]
