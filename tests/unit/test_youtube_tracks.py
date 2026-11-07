"""Streaming YouTube above 360p: HLS playlists of its own video and audio tracks, and MP4 files joined from them."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from sources import MediaStream, MediaTracks, site_for
from sources.ytdlp.source import tracks_of


def _format(format_id, *, vcodec="none", acodec="none", ext="mp4", height=None, tbr=None, **extra):
    return {
        "format_id": format_id, "vcodec": vcodec, "acodec": acodec, "ext": ext, "height": height, "tbr": tbr,
        "protocol": "https", "url": f"https://rr1.googlevideo.com/videoplayback?itag={format_id}&expire=1900000000",
        **extra,
    }


def _box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def _sidx(fragments: list[tuple[int, int]], timescale: int = 1000) -> bytes:
    body = bytes(4) + (1).to_bytes(4, "big") + timescale.to_bytes(4, "big") + bytes(8)
    body += bytes(2) + len(fragments).to_bytes(2, "big")
    for size, duration in fragments:
        body += size.to_bytes(4, "big") + duration.to_bytes(4, "big") + (0x90000000).to_bytes(4, "big")
    return _box(b"sidx", body)


HEAD = _box(b"ftyp", b"dash" + bytes(4)) + _box(b"moov", bytes(20))
TRACK = HEAD + _sidx([(1000, 5000), (2000, 4500)]) + _box(b"moof", bytes(8))


def test_youtube_tracks_are_its_h264_video_per_resolution_and_the_original_audio():
    tracks = tracks_of({"formats": [
        _format("18", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360),
        _format("137", vcodec="avc1.640028", height=1080, width=1920, tbr=4000.5),
        _format("248", vcodec="vp9", ext="webm", height=1080, tbr=9000),
        _format("136", vcodec="avc1.4d401f", height=720),
        _format("134", vcodec="avc1.4d401e", height=360),
        _format("399", vcodec="av01.0.08M.08", height=1080, tbr=9000),
        _format("140-0", acodec="mp4a.40.2", ext="m4a", language_preference=-1),
        _format("140-1", acodec="mp4a.40.2", ext="m4a", language_preference=10, abr=129.5),
        _format("140-drc", acodec="mp4a.40.2", ext="m4a", language_preference=10),
    ]}, (360, 720, 1080))
    assert [track.url.split("itag=")[1].split("&")[0] for track in tracks.video] == ["137", "136", "134"]
    assert tracks.video[0].codecs == "avc1.640028" and tracks.video[0].bitrate == 4_000_500
    assert (tracks.video[0].width, tracks.video[0].height) == (1920, 1080)
    assert "itag=140-1" in tracks.audio.url and tracks.audio.codecs == "mp4a.40.2"
    assert tracks.video[0].expires_at == 1900000000
    assert tracks_of({"formats": [_format("137", vcodec="avc1.640028", height=1080)]}, (1080,)) is None


def test_a_feed_streams_at_the_highest_resolution_up_to_its_format():
    from backend.api.endpoints.feeds.source_tracks import joins_mp4, stream_height

    youtube = site_for("https://www.youtube.com/@channel", "ytdlp")
    assert stream_height(youtube, 1080) == 1080
    assert stream_height(youtube, 480) == 360
    assert stream_height(youtube, None) == 1080
    # 360p is YouTube's own MP4 with sound; the others are joined.
    assert not joins_mp4(youtube, 360) and joins_mp4(youtube, 720)
    assert not joins_mp4(site_for("https://www.dailywire.com/show/x", "dailywire"), 1080)


def test_the_segment_index_gives_every_fragment_of_a_track():
    from backend.api.endpoints.feeds.source_tracks import parse_segment_index

    index = parse_segment_index(TRACK)
    first = len(HEAD) + len(_sidx([(0, 0), (0, 0)]))
    assert index.init_size == len(HEAD)
    assert index.fragments == ((first, 1000, 5.0), (first + 1000, 2000, 4.5))
    assert parse_segment_index(TRACK[:len(HEAD) + 10]) is None


class _Upstream:
    """googlevideo, serving byte ranges of each URL's file."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.ranges: list[tuple[str, str]] = []

    def get(self, url, headers, stream, timeout):
        content = self.files[url]
        self.ranges.append((url, headers["Range"]))
        first, last = (int(value) for value in headers["Range"].removeprefix("bytes=").split("-"))
        if first >= len(content):
            return SimpleNamespace(status_code=416, headers={}, close=lambda: None)
        last = min(last, len(content) - 1)
        body = content[first:last + 1]
        return SimpleNamespace(
            status_code=206, headers={"Content-Range": f"bytes {first}-{last}/{len(content)}"},
            iter_content=lambda size: (body[i:i + size] for i in range(0, len(body), size)), close=lambda: None,
        )


def _tracks(video_url="https://yt/1080", audio_url="https://yt/audio") -> MediaTracks:
    def video(height, url, width):
        return MediaStream(url=url, ready=False, codecs="avc1.640028", bitrate=4_000_000, width=width, height=height)

    return MediaTracks(
        video=(video(1080, video_url, 1920), video(720, "https://yt/720", 1280), video(360, "https://yt/360", 640)),
        audio=MediaStream(url=audio_url, codecs="mp4a.40.2", bitrate=128_000),
    )


class _Source:
    name = "YouTube"

    def __init__(self, tracks):
        self.tracks = tracks
        self.lookups = 0

    def media_tracks(self, url, *, use_cookies=True):
        self.lookups += 1
        return self.tracks


@pytest.fixture
def tracks_module(monkeypatch):
    from backend.api.endpoints.feeds import source_tracks

    from backend.api.endpoints.feeds.upstream import LinkCache

    monkeypatch.setattr(source_tracks, "_tracks", LinkCache(source_tracks._kept_for))
    monkeypatch.setattr(source_tracks, "_indexes", LinkCache(lambda kept: 3600))
    return source_tracks


def _episode(uuid="e1"):
    from backend.api.endpoints.feeds.source_tracks import EpisodeRef

    return EpisodeRef(uuid=uuid, url="https://www.youtube.com/watch?v=abc", use_cookies=False)


def test_the_hls_stream_has_a_variant_per_resolution_up_to_the_feeds(tracks_module):
    source = _Source(_tracks())
    master = tracks_module.master_playlist_response(source, _episode(), height=720, head_only=False).body.decode()
    assert '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="tracks/audio.m3u8"' in master
    assert "tracks/video-1080.m3u8" not in master
    assert master.splitlines()[-4:] == [
        '#EXT-X-STREAM-INF:BANDWIDTH=4128000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1280x720,AUDIO="audio"',
        "tracks/video-720.m3u8",
        '#EXT-X-STREAM-INF:BANDWIDTH=4128000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=640x360,AUDIO="audio"',
        "tracks/video-360.m3u8",
    ]


def test_track_playlists_list_fragments_at_vodloft(tracks_module, monkeypatch):
    upstream = _Upstream({"https://yt/1080": TRACK})
    monkeypatch.setattr(requests, "get", upstream.get)
    source = _Source(_tracks())

    playlist = tracks_module.track_playlist_response(source, _episode(), "video-1080.m3u8", head_only=False)
    lines = playlist.body.decode().splitlines()
    assert playlist.headers["content-type"] == "application/x-mpegURL"
    assert lines[5] == f'#EXT-X-MAP:URI="video-1080.mp4",BYTERANGE="{len(HEAD)}@0"'
    assert lines[6:9] == ["#EXTINF:5.000,", f"#EXT-X-BYTERANGE:1000@{len(HEAD) + len(_sidx([(0, 0), (0, 0)]))}", "video-1080.mp4"]
    assert lines[-1] == "#EXT-X-ENDLIST"
    tracks_module.track_playlist_response(source, _episode(), "video-1080.m3u8", head_only=False)
    # The index was read once, and the tracks looked up once.
    assert len(upstream.ranges) == 1 and source.lookups == 1


def test_a_fragment_redirects_to_youtube_with_a_link_that_has_not_expired(tracks_module, monkeypatch):
    source = _Source(_tracks())
    app = FastAPI()

    @app.get("/{name}")
    def part(name: str, request: Request):
        return tracks_module.track_redirect_response(source, _episode(), name, head_only=False)

    client = TestClient(app, follow_redirects=False)
    response = client.get("/video-1080.mp4")
    assert (response.status_code, response.headers["location"]) == (302, "https://yt/1080")
    assert response.headers["cache-control"].startswith("no-store")
    assert client.get("/audio.mp4").headers["location"] == "https://yt/audio"
    assert client.get("/video-480.mp4").status_code == 404
    # Shortly before the links expire, the next fragment is asked for with newly looked up ones.
    monkeypatch.setattr(tracks_module.time, "time", lambda: 10**12)
    client.get("/audio.mp4")
    assert source.lookups == 2


def test_a_proxied_fragment_is_passed_on_with_its_range(tracks_module, monkeypatch):
    monkeypatch.setattr(requests, "get", _Upstream({"https://yt/audio": b"0123456789"}).get)
    source = _Source(_tracks())
    app = FastAPI()

    @app.get("/{name}")
    def part(name: str, request: Request):
        return tracks_module.track_part_response(source, _episode(), name, range_header=request.headers.get("range"), head_only=False)

    response = TestClient(app).get("/audio.mp4", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-type"] == "audio/mp4"
    assert TestClient(app).get("/video-480.mp4").status_code == 404


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_video_and_audio_tracks_are_joined_into_one_mp4(tracks_module, monkeypatch, tmp_path):
    def made(name, *args):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args, "-t", "2", "-f", "mp4",
                        "-movflags", "+dash+global_sidx", str(path)], check=True)
        return path.read_bytes()

    video = made("v.mp4", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an")
    audio = made("a.m4a", "-f", "lavfi", "-i", "sine=f=440", "-c:a", "aac", "-vn")
    monkeypatch.setattr(requests, "get", _Upstream({"https://yt/v": video, "https://yt/a": audio}).get)
    from backend.api.endpoints.feeds import upstream as feed_upstream

    monkeypatch.setattr(feed_upstream, "UPSTREAM_CHUNK_BYTES", 20_000)
    monkeypatch.setattr(tracks_module, "get_settings", lambda: SimpleNamespace(download_settings=SimpleNamespace(ffmpeg_path="ffmpeg")))

    target = tmp_path / "cache" / "joined.mp4"
    tracks_module._join(MediaStream(url="https://yt/v"), MediaStream(url="https://yt/a"), target)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(target)],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.split() == ["video", "audio"]
    # The index is at the front, so apps can play and seek in it at once.
    assert target.read_bytes().find(b"moov") < target.read_bytes().find(b"mdat")
    assert [path.name for path in target.parent.iterdir()] == ["joined.mp4"]


def test_an_mp4_plays_youtubes_own_file_until_the_joined_one_is_ready(tracks_module, monkeypatch, tmp_path):
    from backend.api.endpoints.feeds import router as feeds

    joined = tmp_path / "joined.mp4"
    ready: dict[str, Path] = {}
    started = []
    monkeypatch.setattr(tracks_module, "get_cached_mp4_path", lambda key: ready.get(key))
    monkeypatch.setattr(feeds, "join_in_background", lambda source, episode, height: started.append((episode.uuid, height)))
    monkeypatch.setattr(feeds, "episode_stream", lambda source, episode, audio: MediaStream(url="https://yt/18"))
    monkeypatch.setattr(feeds, "proxy_response", lambda *args, **kwargs: feeds.Response(b"through VODLoft"))
    monkeypatch.setattr(feeds, "uses_cookies", lambda collection: False)
    monkeypatch.setattr(tracks_module, "_file_streamed", {})

    def profile(proxy):
        return SimpleNamespace(
            collection=SimpleNamespace(sharing_url="https://www.youtube.com/@channel", source_key="ytdlp"),
            preferred_format="format_1080p", proxy_source_stream=proxy,
        )

    episode = SimpleNamespace(uuid="e1", slug="e1", sharing_url="https://www.youtube.com/watch?v=abc", collection=None)
    app = FastAPI()

    @app.get("/{proxy}")
    def media(proxy: str, request: Request):
        return feeds._site_video_mp4(object(), profile(proxy == "proxy"), episode, request)

    client = TestClient(app, follow_redirects=False)
    first = client.get("/direct")
    assert first.status_code == 302 and first.headers["location"] == "https://yt/18"
    assert started == [("e1", 1080)]
    assert client.get("/proxy").content == b"through VODLoft"

    # Ready now, but an app that was playing YouTube's file keeps getting it for a while.
    joined.write_bytes(b"joined")
    ready["e1-1080p"] = joined
    assert client.get("/direct").status_code == 302
    tracks_module._file_streamed.clear()
    assert client.get("/direct").content == b"joined"
