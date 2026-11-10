"""Streaming YouTube episodes that are not downloaded, through VODLoft itself."""
from __future__ import annotations

import io
import time
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from sources import MediaStream, StreamMethod, get_source, site_for
from sources.ytdlp.source import stream_of


def _format(format_id, *, vcodec="none", acodec="mp4a.40.2", protocol="https", abr=None, size=None, url=None, language_preference=None):
    return {
        "format_id": format_id, "vcodec": vcodec, "acodec": acodec, "protocol": protocol, "abr": abr,
        "language_preference": language_preference,
        "filesize": size, "url": url or f"https://rr1.googlevideo.com/videoplayback?itag={format_id}&expire=1900000000",
        "http_headers": {"User-Agent": "yt-dlp"},
    }


def test_youtube_and_the_daily_wire_stream_but_other_sites_do_not():
    # YouTube and The Daily Wire stream files, HLS and live episodes.
    youtube = site_for("https://www.youtube.com/@channel", "ytdlp")
    assert youtube.stream_methods == {StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE}
    assert youtube.stream_video_heights == (360, 720, 1080) and youtube.stream_file_height == 360
    assert youtube.stream_proxy_choice
    dailywire = site_for("https://www.dailywire.com/show/the-ben-shapiro-show", "dailywire")
    assert dailywire.stream_methods == {StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE}
    for url in ("https://vimeo.com/channels/staffpicks", "https://example.org/videos"):
        site = site_for(url, "ytdlp")
        assert not site.streams and not site.stream_methods


def test_audio_is_youtubes_m4a_when_it_is_offered():
    stream = stream_of({"formats": [
        _format("251", acodec="opus", abr=160), _format("140", abr=129, size=1234),
        _format("18", vcodec="avc1"), _format("hls-1", protocol="m3u8_native"),
    ]}, audio=True)
    assert stream is not None and stream.ready
    assert "itag=140" in stream.url
    assert stream.size_bytes == 1234
    assert stream.expires_at == 1900000000
    assert stream.headers == {"User-Agent": "yt-dlp"}


def test_a_dubbed_video_plays_the_m4a_of_its_original_language():
    stream = stream_of({"formats": [
        _format("140-drc", abr=129, language_preference=10), _format("140-0", abr=129, language_preference=-1),
        _format("140-1", abr=129, language_preference=10), _format("140-2", abr=129, language_preference=-1),
    ]}, audio=True)
    assert stream is not None and stream.ready
    assert "itag=140-1" in stream.url


def test_audio_without_m4a_is_the_best_audio_to_transcode():
    stream = stream_of({"formats": [
        _format("249", acodec="opus", abr=50), _format("251", acodec="opus", abr=160),
        _format("140-drc", abr=200, protocol="m3u8_native"),
    ]}, audio=True)
    assert stream is not None and not stream.ready
    assert "itag=251" in stream.url


def test_video_is_only_the_mp4_with_sound():
    assert "itag=18" in stream_of({"formats": [_format("137", vcodec="avc1", acodec="none"), _format("18", vcodec="avc1")]}, audio=False).url
    assert stream_of({"formats": [_format("137", vcodec="avc1", acodec="none"), _format("140")]}, audio=False) is None


def test_a_missing_stream_is_looked_up_again_soon():
    from backend.api.endpoints.feeds import source_stream

    assert source_stream._kept_for(None) <= 2 * 60


def test_a_site_that_cannot_stream_is_not_looked_up():
    with pytest.raises(NotImplementedError):
        get_source("ytdlp").media_stream("https://vimeo.com/123456", audio=True)


def test_a_feed_on_a_site_that_cannot_stream_is_refused():
    from backend.api.endpoints.rss_stream_profiles.service import ensure_site_can_stream

    vimeo = SimpleNamespace(sharing_url="https://vimeo.com/channels/staffpicks", source_key="ytdlp")
    youtube = SimpleNamespace(sharing_url="https://www.youtube.com/@channel-for-refusals", source_key="ytdlp")
    mp4 = {"preferred_format": "format_1080p", "video_output_mode": "audio_mp4"}
    with pytest.raises(HTTPException) as refused:
        ensure_site_can_stream(vimeo, use_source_stream=True, stream_live_episodes=False, **mp4)
    assert refused.value.status_code == 422
    ensure_site_can_stream(youtube, use_source_stream=True, stream_live_episodes=False, **mp4)
    ensure_site_can_stream(
        youtube, use_source_stream=True, stream_live_episodes=False, preferred_format="format_audio_only", video_output_mode=None,
    )
    ensure_site_can_stream(
        youtube, use_source_stream=True, stream_live_episodes=False, preferred_format="format_1080p",
        video_output_mode="audio_hls",
    )
    # YouTube streams 360p, 720p and 1080p; downloads can have any resolution.
    with pytest.raises(HTTPException, match="has no 480p video"):
        ensure_site_can_stream(youtube, use_source_stream=True, stream_live_episodes=False, preferred_format="format_480p",
                               video_output_mode="audio_hls")
    ensure_site_can_stream(youtube, use_source_stream=False, stream_live_episodes=False, preferred_format="format_480p",
                           video_output_mode="mp4")
    # Without streaming, HLS comes from downloads, so any output works.
    ensure_site_can_stream(
        youtube, use_source_stream=False, stream_live_episodes=False, preferred_format="format_1080p", video_output_mode="mp4_hls",
    )
    ensure_site_can_stream(youtube, use_source_stream=True, stream_live_episodes=True, **mp4)
    with pytest.raises(HTTPException, match="cannot stream live episodes"):
        ensure_site_can_stream(vimeo, use_source_stream=False, stream_live_episodes=True, **mp4)


class _Upstream:
    """googlevideo, serving byte ranges of a file; ``refuse`` answers 403 that many times first."""

    def __init__(self, content: bytes, refuse: int = 0):
        self.content = content
        self.refuse = refuse
        self.ranges: list[str] = []

    def get(self, url, headers, stream, timeout):
        self.ranges.append(headers["Range"])
        if self.refuse:
            self.refuse -= 1
            return SimpleNamespace(status_code=403, headers={}, close=lambda: None)
        first, last = (int(value) for value in headers["Range"].removeprefix("bytes=").split("-"))
        last = min(last, len(self.content) - 1)
        body = self.content[first:last + 1]
        return SimpleNamespace(
            status_code=206, headers={"Content-Range": f"bytes {first}-{last}/{len(self.content)}"},
            iter_content=lambda size: (body[i:i + size] for i in range(0, len(body), size)), close=lambda: None,
        )


def _episode(duration=10.0):
    return SimpleNamespace(
        uuid=f"episode-{id(object())}", sharing_url="https://www.youtube.com/watch?v=abc", duration=duration,
        collection=SimpleNamespace(cookies_mode="automatic", cookies_needed_until=None),
    )


class _Source:
    name = "YouTube"

    def __init__(self, *streams):
        self.streams = list(streams)
        self.lookups = 0

    def media_stream(self, url, *, audio, use_cookies=True):
        self.lookups += 1
        return self.streams[min(self.lookups, len(self.streams)) - 1]


@pytest.fixture
def proxied(monkeypatch):
    from backend.api.endpoints.feeds import source_stream

    monkeypatch.setattr(source_stream, "uses_cookies", lambda collection: True)
    from backend.api.endpoints.feeds import upstream

    monkeypatch.setattr(upstream, "UPSTREAM_CHUNK_BYTES", 4)
    return source_stream


def _client(response_for):
    app = FastAPI()

    @app.api_route("/media", methods=["GET", "HEAD"])
    def media(request: Request):
        return response_for(request.headers.get("range"), request.method == "HEAD")

    return TestClient(app)


def test_m4a_is_passed_on_range_by_range(proxied, monkeypatch):
    upstream = _Upstream(b"0123456789abcdef")
    monkeypatch.setattr(requests, "get", upstream.get)
    source = _Source(MediaStream(url="https://rr1.googlevideo.com/a", size_bytes=16))
    episode = _episode()
    client = _client(lambda range_header, head_only: proxied.proxy_response(
        source, episode, audio=True, media_type="audio/mp4", filename="e.m4a", range_header=range_header, head_only=head_only,
    ))

    whole = client.get("/media")
    assert whole.status_code == 200
    assert whole.content == b"0123456789abcdef"
    assert whole.headers["content-length"] == "16"
    assert whole.headers["accept-ranges"] == "bytes"
    # YouTube is asked in small ranges, never for the whole file at once.
    assert upstream.ranges == ["bytes=0-3", "bytes=4-7", "bytes=8-11", "bytes=12-15"]

    part = client.get("/media", headers={"Range": "bytes=5-9"})
    assert part.status_code == 206
    assert part.content == b"56789"
    assert part.headers["content-range"] == "bytes 5-9/16"

    head = client.head("/media", headers={"Range": "bytes=10-"})
    assert head.status_code == 206
    assert head.headers["content-length"] == "6"
    # The stream was looked up once and kept for every request after it.
    assert source.lookups == 1


def test_a_refused_url_is_looked_up_again(proxied, monkeypatch):
    upstream = _Upstream(b"abcd", refuse=1)
    monkeypatch.setattr(requests, "get", upstream.get)
    source = _Source(MediaStream(url="https://old"), MediaStream(url="https://new"))
    response = _client(lambda range_header, head_only: proxied.proxy_response(
        source, _episode(), audio=True, media_type="audio/mp4", filename="e.m4a", range_header=range_header, head_only=head_only,
    )).get("/media")
    assert response.status_code == 200
    assert response.content == b"abcd"
    assert source.lookups == 2


def test_a_new_link_youtube_still_refuses_is_asked_for_again(proxied, monkeypatch):
    # YouTube now and then refuses a link it has just handed out, and accepts it moments later.
    upstream = _Upstream(b"abcd", refuse=3)
    monkeypatch.setattr(requests, "get", upstream.get)
    from backend.api.endpoints.feeds import upstream as upstream_module

    waits: list[float] = []
    monkeypatch.setattr(upstream_module.time, "sleep", waits.append)
    source = _Source(MediaStream(url="https://old"), MediaStream(url="https://new"))
    response = _client(lambda range_header, head_only: proxied.proxy_response(
        source, _episode(), audio=False, media_type="video/mp4", filename="e.mp4", range_header=range_header, head_only=head_only,
    )).get("/media")
    assert response.status_code == 200
    assert response.content == b"abcd"
    # One more lookup, and then the same link again after a short wait each time.
    assert source.lookups == 2
    assert waits == [1.0, 2.0]


def test_a_link_youtube_keeps_refusing_is_given_up(proxied, monkeypatch):
    monkeypatch.setattr(requests, "get", _Upstream(b"abcd", refuse=10).get)
    from backend.api.endpoints.feeds import upstream as upstream_module

    monkeypatch.setattr(upstream_module.time, "sleep", lambda seconds: None)
    with pytest.raises(HTTPException) as refused:
        proxied.proxy_response(
            _Source(MediaStream(url="https://old")), _episode(), audio=False, media_type="video/mp4", filename="e.mp4",
            range_header=None, head_only=False,
        )
    assert refused.value.status_code == 502


def test_an_episode_without_a_stream_is_not_found(proxied):
    with pytest.raises(HTTPException) as missing:
        proxied.proxy_response(
            _Source(None), _episode(), audio=False, media_type="video/mp4", filename="e.mp4", range_header=None, head_only=False,
        )
    assert missing.value.status_code == 404


class _Ffmpeg:
    """ffmpeg writing ``output`` and remembering the command it was started with."""

    commands: list[list[str]] = []

    def __init__(self, output: bytes):
        self.output = output

    def __call__(self, command, stdout, stderr):
        self.commands.append(command)
        return SimpleNamespace(stdout=io.BytesIO(self.output), kill=lambda: None, wait=lambda: None)


def test_other_audio_is_transcoded_to_exactly_the_estimated_size(proxied, monkeypatch):
    ffmpeg = _Ffmpeg(b"\xff\xf1" * 100_000)
    monkeypatch.setattr(proxied.subprocess, "Popen", ffmpeg)
    source = _Source(MediaStream(url="https://rr1.googlevideo.com/opus", headers={"User-Agent": "yt-dlp"}, ready=False))
    episode = _episode(duration=10.0)
    client = _client(lambda range_header, head_only: proxied.proxy_response(
        source, episode, audio=True, media_type="audio/mp4", filename="e.m4a", range_header=range_header, head_only=head_only,
    ))

    whole = client.get("/media")
    # Ten seconds at 128 kbit/s: the length the feed gives the episode too.
    assert proxied.estimated_audio_size(10.0) == 160_000
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "audio/aac"
    assert len(whole.content) == 160_000
    assert "-ss" not in ffmpeg.commands[-1]
    assert ffmpeg.commands[-1][ffmpeg.commands[-1].index("-user_agent") + 1] == "yt-dlp"
    assert ffmpeg.commands[-1][-3:] == ["-f", "adts", "pipe:1"]

    # A seek starts the transcode at the time the byte stands for, and a short transcode is filled up.
    monkeypatch.setattr(proxied.subprocess, "Popen", _Ffmpeg(b"\xff\xf1" * 10))
    seek = client.get("/media", headers={"Range": "bytes=80000-"})
    assert seek.status_code == 206
    assert seek.headers["content-range"] == "bytes 80000-159999/160000"
    assert len(seek.content) == 80_000
    command = _Ffmpeg.commands[-1]
    assert command[command.index("-ss") + 1] == "5.000"


def test_audio_enclosures_give_their_estimated_size():
    from backend.api.endpoints.feeds.source_stream import estimated_audio_size

    assert estimated_audio_size(3600) == 57_600_000
    assert estimated_audio_size(None) is None
    assert estimated_audio_size(0) is None


def test_video_gives_an_estimated_size_by_resolution():
    from backend.api.endpoints.feeds.source_stream import estimated_video_size

    assert estimated_video_size(3600, 360) == 225_000_000
    assert estimated_video_size(3600, 720) == 900_000_000
    assert estimated_video_size(3600, 1080) == 1_350_000_000
    assert estimated_video_size(3600, None) == 1_350_000_000
    assert estimated_video_size(3600, 2160) == 3_600_000_000
    assert estimated_video_size(None, 1080) is None
