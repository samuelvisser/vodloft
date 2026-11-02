"""Video stills: YouTube's in their widest form, and a frame of the video when there is none.

yt-dlp often names a video's hqdefault or sddefault still. Those are 4:3 frames, so a 16:9 video gets
black bars inside the picture. maxresdefault is the 16:9 still, but YouTube only makes it for videos
uploaded in high resolution, so it is used only when YouTube serves it.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

import requests

from config import get_settings
from .. import ytdlp_runner as runner

logger = logging.getLogger(__name__)

_STILL = re.compile(
    r"^(?P<base>https?://i\d?\.ytimg\.com/vi(?P<webp>_webp)?/[\w-]{11}/)(?:hq|sd|mq)?default\.(?:jpg|webp)(?:\?.*)?$"
)
_ANY_STILL = re.compile(r"^https?://i\d?\.ytimg\.com/vi(?:_webp)?/[\w-]{11}/")
_TIMEOUT_SECONDS = 5
# Small streams are enough for a thumbnail and start quickly.
_FRAME_FORMAT = "bv*[height<=720]/b[height<=720]/bv*/b"
_FRAME_SECONDS = "3"
_FRAME_TIMEOUT_SECONDS = 60


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


def still_missing(url: str | None) -> bool:
    """Whether a video has no picture: none at all, or a YouTube still YouTube has not made.

    YouTube answers such a still with a grey placeholder and HTTP 404. Pictures
    on other sites are taken as they are.
    """
    if not url:
        return True
    if _ANY_STILL.match(url) is None:
        return False
    try:
        response = requests.head(url, timeout=_TIMEOUT_SECONDS, allow_redirects=True)
    except requests.RequestException:
        return False
    return response.status_code == 404


def first_frame(url: str) -> bytes | None:
    """A JPEG of the start of a video, like the still YouTube makes itself.

    ffmpeg reads only the first seconds of the stream and keeps the frame that
    best represents them, so a fade in from black does not become the picture.
    """
    ffmpeg = get_settings().download_settings.ffmpeg_path
    if shutil.which(ffmpeg) is None:
        logger.info("Not taking a frame of %s, because ffmpeg is not installed", url)
        return None
    try:
        info = runner.run_json("--no-playlist", "-f", _FRAME_FORMAT, url)
    except runner.YtDlpError as exc:
        logger.info("Not taking a frame of %s: %s", url, exc)
        return None
    stream = info.get("url")
    if not stream:
        logger.info("Not taking a frame of %s, because yt-dlp named no single stream", url)
        return None
    headers = "".join(f"{name}: {value}\r\n" for name, value in (info.get("http_headers") or {}).items())
    command = [ffmpeg, "-nostdin", "-loglevel", "error"]
    if headers:
        command += ["-headers", headers]
    command += [
        "-t", _FRAME_SECONDS, "-i", stream, "-vf", "thumbnail,scale='min(1280,iw)':-2",
        "-frames:v", "1", "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=_FRAME_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        logger.info("Not taking a frame of %s, because ffmpeg took too long", url)
        return None
    if result.returncode != 0 or not result.stdout:
        logger.info("Not taking a frame of %s: %s", url, result.stderr.decode(errors="replace").strip()[-300:])
        return None
    return result.stdout
