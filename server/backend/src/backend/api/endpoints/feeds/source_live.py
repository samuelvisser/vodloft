"""Streaming an episode while it is live, from a Site whose episodes are listed, such as YouTube.

The Site keeps a live HLS media playlist per resolution, and often one for the sound alone. VODLoft
writes the master playlist over them and hands out each one as the Site has it at that moment, with
its parts straight from the Site or, when the feed proxies its Site's video, through VODLoft. Podcast
apps play live audio badly, so the audio enclosure of a live episode is the sound as one endless AAC
stream, and the apps that can play the video use the HLS alternate enclosure instead.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import subprocess
from collections.abc import Iterator
from urllib.parse import quote, urljoin

import requests
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse

from config import get_settings
from sources import LiveStream, MediaStream, Source

from .source_tracks import HLS_MIME_TYPE, EpisodeRef
from .upstream import NO_CACHE_HEADERS, LinkCache, look_up_at_site


logger = logging.getLogger(__name__)

_KEEP_SECONDS = 20 * 60
_MISSING_SECONDS = 60
_TIMEOUT_SECONDS = 30
_READ_BYTES = 64 * 1024
_PLAYLIST_NAME = re.compile(r"^(?:video-(\d+)|audio)\.m3u8$")
# Signs the Site's part links that a proxied playlist hands out, so the part route only passes on what
# VODLoft itself listed. A restart makes new keys; apps fetch a live playlist again every few seconds.
_PART_KEY = secrets.token_bytes(32)


_kept: LinkCache[str, LiveStream | None] = LinkCache(lambda live: _KEEP_SECONDS if live else _MISSING_SECONDS)


def episode_live(source: Source, episode: EpisodeRef, *, fresh: bool = False) -> LiveStream:
    """The episode's live playlists, looked up once and kept for a while: the Site's links to them
    last for hours, and each one lists the newest parts whenever it is fetched."""
    live = _kept.get(
        episode.uuid,
        lambda: look_up_at_site(
            source, "live stream", episode.url, lambda: source.live_stream(episode.url, use_cookies=episode.use_cookies),
        ),
        fresh=fresh,
    )
    if live is None:
        raise HTTPException(status_code=404, detail=f"This episode is not live on {source.name}")
    return live


def live_master_playlist(live: LiveStream, height: int) -> str:
    """A variant per resolution up to ``height``, from the highest down, sharing the separate sound."""
    videos = [video for video in live.video if (video.height or 0) <= height] or [live.video[-1]]
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS"]
    if live.audio is not None:
        lines.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="live/audio.m3u8"')
    for video in videos:
        audio_bitrate = (live.audio.bitrate or 128_000) if live.audio is not None else 0
        attributes = [f"BANDWIDTH={(video.bitrate or 1_000_000) + audio_bitrate}"]
        if video.width and video.height:
            attributes.append(f"RESOLUTION={video.width}x{video.height}")
        codecs = f"{video.codecs},{live.audio.codecs}" if live.audio is not None and live.audio.codecs else video.codecs
        if codecs:
            attributes.append(f'CODECS="{codecs}"')
        if live.audio is not None:
            attributes.append('AUDIO="audio"')
        lines += [f"#EXT-X-STREAM-INF:{','.join(attributes)}", f"live/video-{video.height}.m3u8"]
    return "\n".join(lines) + "\n"


def _playlist_response(text: str, *, head_only: bool) -> Response:
    content = text.encode()
    headers = {**NO_CACHE_HEADERS, "Content-Type": HLS_MIME_TYPE, "Content-Length": str(len(content))}
    return Response(content=b"" if head_only else content, headers=headers)


def live_master_response(source: Source, episode: EpisodeRef, *, height: int, head_only: bool) -> Response:
    return _playlist_response(live_master_playlist(episode_live(source, episode), height), head_only=head_only)


def _signature(url: str) -> str:
    return hmac.new(_PART_KEY, url.encode(), hashlib.sha256).hexdigest()


def rewrite_playlist(text: str, base_url: str, *, part_base: str | None) -> str:
    """Every link in the Site's playlist made absolute, or through VODLoft's part route at ``part_base``."""
    def link(uri: str) -> str:
        absolute = urljoin(base_url, uri)
        return f"{part_base}?u={quote(absolute, safe='')}&s={_signature(absolute)}" if part_base else absolute

    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            out.append(link(stripped))
        elif 'URI="' in line:
            before, _, rest = line.partition('URI="')
            uri, _, after = rest.partition('"')
            out.append(f'{before}URI="{link(uri)}"{after}')
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _named(live: LiveStream, name: str) -> MediaStream:
    match = _PLAYLIST_NAME.match(name)
    if match is None:
        raise HTTPException(status_code=404, detail="No such playlist")
    if match.group(1) is None:
        if live.audio is None:
            raise HTTPException(status_code=404, detail="No such playlist")
        return live.audio
    stream = next((video for video in live.video if video.height == int(match.group(1))), None)
    if stream is None:
        raise HTTPException(status_code=404, detail="No such playlist")
    return stream


def live_playlist_response(
        source: Source, episode: EpisodeRef, name: str, *, part_base: str | None, head_only: bool,
) -> Response:
    """One of the Site's live playlists as it is now; its link is looked up again once when refused."""
    status = None
    for fresh in (False, True):
        stream = _named(episode_live(source, episode, fresh=fresh), name)
        upstream = requests.get(stream.url, headers=dict(stream.headers), timeout=_TIMEOUT_SECONDS)
        if upstream.status_code == 200:
            return _playlist_response(rewrite_playlist(upstream.text, stream.url, part_base=part_base), head_only=head_only)
        status = upstream.status_code
        logger.info("%s answered %s for a live playlist of %s", source.name, status, episode.url)
    raise HTTPException(status_code=502, detail=f"{source.name} answered {status} for the live playlist")


def live_part_response(url: str, signature: str, *, range_header: str | None, head_only: bool) -> Response:
    """A part the proxied playlist listed, passed on from the Site."""
    if not hmac.compare_digest(signature, _signature(url)):
        raise HTTPException(status_code=404, detail="No such part")
    upstream = requests.get(url, headers={"Range": range_header} if range_header else {}, stream=True, timeout=_TIMEOUT_SECONDS)
    if upstream.status_code not in (200, 206):
        upstream.close()
        raise HTTPException(status_code=502, detail=f"The site answered {upstream.status_code} for a live part")
    passed = {name: upstream.headers[name] for name in ("Content-Length", "Content-Range") if name in upstream.headers}
    headers = {**NO_CACHE_HEADERS, "Content-Type": upstream.headers.get("Content-Type", "video/mp2t"), **passed}
    if head_only:
        upstream.close()
        return Response(status_code=upstream.status_code, headers=headers)

    def body() -> Iterator[bytes]:
        try:
            yield from upstream.iter_content(_READ_BYTES)
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=headers)


def _ffmpeg_input(stream: MediaStream) -> list[str]:
    headers = dict(stream.headers)
    command = []
    agent = headers.pop("User-Agent", None)
    if agent:
        command += ["-user_agent", agent]
    if headers:
        command += ["-headers", "".join(f"{name}: {value}\r\n" for name, value in headers.items())]
    return [*command, "-i", stream.url]


def live_audio_response(source: Source, episode: EpisodeRef, *, head_only: bool) -> Response:
    """The sound of the live episode as one endless AAC stream, without a length or seeking."""
    headers = {**NO_CACHE_HEADERS, "Content-Type": "audio/aac"}
    live = episode_live(source, episode)
    if head_only:
        return Response(status_code=200, headers=headers)
    sound = live.audio or live.video[-1]
    command = [
        str(get_settings().download_settings.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-nostdin",
        *_ffmpeg_input(sound), "-vn", "-map", "0:a:0", "-c:a", "copy", "-f", "adts", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def body() -> Iterator[bytes]:
        try:
            while chunk := process.stdout.read(_READ_BYTES):
                yield chunk
        finally:
            process.kill()
            process.wait()

    return StreamingResponse(body(), headers=headers)
