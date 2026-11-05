"""EXPERIMENT: the YouTube video streaming methods pick the right formats and rewrite HLS playlists."""
from __future__ import annotations

from backend.api.endpoints.feeds import youtube_experiments as experiments


def _fmt(format_id, *, vcodec="none", acodec="none", protocol="https", ext="mp4", height=None, tbr=None):
    return {
        "format_id": format_id, "vcodec": vcodec, "acodec": acodec, "protocol": protocol, "ext": ext,
        "height": height, "tbr": tbr, "url": f"https://rr1.googlevideo.com/videoplayback?itag={format_id}",
    }


INFO = {"formats": [
    _fmt("18", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360),
    _fmt("22", vcodec="avc1.64001F", acodec="mp4a.40.2", height=720),
    _fmt("137", vcodec="avc1.640028", height=1080),
    _fmt("136", vcodec="avc1.4d401f", height=720),
    _fmt("247", vcodec="vp9", ext="webm", height=720),
    _fmt("140", acodec="mp4a.40.2", ext="m4a"),
    _fmt("95", vcodec="avc1.4d401f", acodec="mp4a.40.2", protocol="m3u8_native", height=720),
    _fmt("96", vcodec="avc1.640028", acodec="mp4a.40.2", protocol="m3u8_native", height=1080),
]}


def test_each_method_picks_its_format():
    assert experiments._pick(INFO, "proxy")["format_id"] == "18"
    assert experiments._pick(INFO, "client-tv")["format_id"] == "18"
    assert experiments._pick(INFO, "muxed")["format_id"] == "22"
    assert experiments._pick(INFO, "hls-proxy")["format_id"] == "95"
    assert experiments._video_for_remux(INFO)["format_id"] == "136"
    assert experiments._audio_m4a(INFO)["format_id"] == "140"


def test_hls_playlists_point_at_youtube_or_through_vodloft():
    playlist = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:5,\nseg/1.ts\n'
    base = "https://rr1.googlevideo.com/hls/playlist/index.m3u8"
    assert experiments._rewrite_playlist(playlist, base, None).splitlines() == [
        "#EXTM3U", '#EXT-X-MAP:URI="https://rr1.googlevideo.com/hls/playlist/init.mp4"', "#EXTINF:5,",
        "https://rr1.googlevideo.com/hls/playlist/seg/1.ts",
    ]
    proxied = experiments._rewrite_playlist(playlist, base, lambda url: f"/segment?u={url}")
    assert proxied.splitlines()[-1] == "/segment?u=https://rr1.googlevideo.com/hls/playlist/seg/1.ts"
    assert experiments._allowed("https://rr1---sn-abc.googlevideo.com/x")
    assert not experiments._allowed("https://example.com/x")
