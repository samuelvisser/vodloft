"""YouTube stills in their widest form.

yt-dlp often names a video's hqdefault or sddefault still. Those are 4:3 frames, so a 16:9 video gets
black bars inside the picture. maxresdefault is the 16:9 still, but YouTube only makes it for videos
uploaded in high resolution, so it is used only when YouTube serves it.
"""
from __future__ import annotations

import re

import requests

_STILL = re.compile(
    r"^(?P<base>https?://i\d?\.ytimg\.com/vi(?P<webp>_webp)?/[\w-]{11}/)(?:hq|sd|mq)?default\.(?:jpg|webp)(?:\?.*)?$"
)
_TIMEOUT_SECONDS = 5


def widest_still(url: str | None) -> str | None:
    """The maxresdefault still for a YouTube still URL when YouTube has one; any other URL as given."""
    match = _STILL.match(url or "")
    if match is None:
        return url
    candidate = f"{match['base']}maxresdefault.{'webp' if match['webp'] else 'jpg'}"
    try:
        response = requests.head(candidate, timeout=_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException:
        return url
    return candidate if response.status_code == 200 else url
