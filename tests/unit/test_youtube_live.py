"""A YouTube video plays in a feed while it is live: VODLoft writes the master playlist over YouTube's own
live playlists, with the sound YouTube lists apart, and hands those out with parts from YouTube or
through VODLoft."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from sources import LiveStream, MediaStream, StreamMethod, site_for
from sources.ytdlp.source import live_of


def _playlist(format_id, *, height=None, vcodec="avc1.64002A", acodec="none", tbr=None):
    return {
        "format_id": format_id, "protocol": "m3u8_native", "height": height, "width": height * 16 // 9 if height else None,
        "vcodec": vcodec, "acodec": acodec, "tbr": tbr,
        "url": f"https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/{format_id}/index.m3u8",
    }


# As yt-dlp lists a live YouTube video: video without sound, and the sound as 233 and 234 without a codec.
LIVE_INFO = {"live_status": "is_live", "formats": [
    _playlist("312", height=1080, tbr=5552), _playlist("311", height=720, tbr=2922), _playlist("230", height=360, tbr=962),
    _playlist("301", height=1440, tbr=9000), _playlist("233", vcodec="none", acodec=None), _playlist("234", vcodec="none", acodec=None),
]}


def test_youtube_streams_live_episodes():
    assert StreamMethod.LIVE in site_for("https://www.youtube.com/@channel", "ytdlp").stream_methods
    assert StreamMethod.LIVE not in site_for("https://vimeo.com/channel", "ytdlp").stream_methods


def test_a_live_video_has_a_playlist_per_resolution_and_its_sound_apart():
    live = live_of(LIVE_INFO, (360, 720, 1080))
    assert [video.height for video in live.video] == [1080, 720, 360]
    assert live.audio.url.endswith("/itag/234/index.m3u8") and live.audio.codecs == "mp4a.40.2"
    # Variants with their own sound need no separate audio.
    with_sound = {"live_status": "is_live", "formats": [_playlist("301", height=1080, acodec="mp4a.40.2", tbr=5552)]}
    assert live_of(with_sound, (360, 720, 1080)).audio is None
    assert live_of({**LIVE_INFO, "live_status": "was_live"}, (360, 720, 1080)) is None


def test_the_master_playlist_shares_the_sound_up_to_the_feeds_resolution():
    from backend.api.endpoints.feeds.source_live import live_master_playlist

    live = live_of(LIVE_INFO, (360, 720, 1080))
    lines = live_master_playlist(live, 720).splitlines()
    assert lines[3] == '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="live/audio.m3u8"'
    assert lines[4:] == [
        '#EXT-X-STREAM-INF:BANDWIDTH=3050000,RESOLUTION=1280x720,CODECS="avc1.64002A,mp4a.40.2",AUDIO="audio"',
        "live/video-720.m3u8",
        '#EXT-X-STREAM-INF:BANDWIDTH=1090000,RESOLUTION=640x360,CODECS="avc1.64002A,mp4a.40.2",AUDIO="audio"',
        "live/video-360.m3u8",
    ]


def test_live_parts_come_from_youtube_or_through_vodloft_only_as_listed(monkeypatch):
    from backend.api.endpoints.feeds import source_live

    text = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:7\n#EXTINF:5.0,\nsq/7/part.ts\n"
    base = "https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/312/index.m3u8"
    direct = source_live.rewrite_playlist(text, base, part_base=None)
    assert direct.splitlines()[-1] == "https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/312/sq/7/part.ts"
    proxied = source_live.rewrite_playlist(text, base, part_base="part").splitlines()[-1]
    assert proxied.startswith("part?u=https%3A%2F%2Fmanifest.googlevideo.com%2F") and "&s=" in proxied

    # Only a part VODLoft signed is passed on.
    with pytest.raises(HTTPException) as refused:
        source_live.live_part_response("https://example.com/anything", "0" * 64, range_header=None, head_only=True)
    assert refused.value.status_code == 404


def test_a_live_playlist_is_looked_up_again_when_youtube_refuses_its_link(monkeypatch):
    from backend.api.endpoints.feeds import source_live
    from backend.api.endpoints.feeds.source_tracks import EpisodeRef

    looked_up = []

    class FakeSource:
        name = "yt-dlp"

        def live_stream(self, url, *, use_cookies=True):
            looked_up.append(url)
            return LiveStream(
                video=(MediaStream(url=f"https://example.test/{len(looked_up)}/video.m3u8", height=720),),
                audio=MediaStream(url=f"https://example.test/{len(looked_up)}/audio.m3u8"),
            )

    class Answer:
        def __init__(self, status, text=""):
            self.status_code, self.text = status, text

    answers = iter([Answer(403), Answer(200, "#EXTM3U\n#EXTINF:5.0,\npart.ts\n")])
    monkeypatch.setattr(source_live.requests, "get", lambda url, **_kwargs: next(answers))
    episode = EpisodeRef(uuid="live-episode", url="https://www.youtube.com/watch?v=x", use_cookies=False)
    response = source_live.live_playlist_response(FakeSource(), episode, "audio.m3u8", part_base=None, head_only=False)
    assert response.body.decode().splitlines()[-1] == "https://example.test/2/part.ts"
    assert len(looked_up) == 2
    with pytest.raises(HTTPException):
        source_live.live_playlist_response(FakeSource(), episode, "video-1080.m3u8", part_base=None, head_only=False)
