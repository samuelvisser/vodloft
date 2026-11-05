"""EXPERIMENT: the YouTube live streaming methods pick live variants and rewrite their playlists."""
from __future__ import annotations

from backend.api.endpoints.feeds import youtube_experiments as experiments


def _fmt(format_id, *, height, protocol="m3u8_native", vcodec="avc1.4D401E", acodec="mp4a.40.2", tbr=1000):
    return {
        "format_id": format_id, "height": height, "width": height * 16 // 9, "protocol": protocol, "vcodec": vcodec,
        "acodec": acodec, "tbr": tbr, "url": f"https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/{format_id}/index.m3u8",
    }


def test_live_variants_are_the_hls_ones_with_video_up_to_1080p():
    info = {"formats": [
        _fmt("91", height=144), _fmt("96", height=1080), _fmt("301", height=1440), _fmt("93", height=360),
        _fmt("137", height=1080, protocol="http_dash_segments"),
    ]}
    assert [fmt["format_id"] for fmt in experiments.live_variants(info)] == ["96", "93", "91"]
    master = experiments.master_playlist(experiments.live_variants(info)[:1])
    assert master.splitlines()[-2:] == [
        '#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1920x1080,CODECS="avc1.4D401E,mp4a.40.2"', "variant-96.m3u8",
    ]


def test_variant_playlists_point_at_youtube_or_through_vodloft():
    playlist = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:5\n#EXTINF:5,\nsq/5/file.ts\n"
    base = "https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/96/index.m3u8"
    assert experiments.rewrite_playlist(playlist, base, None).splitlines()[-1] == (
        "https://manifest.googlevideo.com/api/manifest/hls_playlist/itag/96/sq/5/file.ts"
    )
    proxied = experiments.rewrite_playlist(playlist, "https://rr1.googlevideo.com/x/", lambda url: f"/segment?u={url}")
    assert proxied.splitlines()[-1] == "/segment?u=https://rr1.googlevideo.com/x/sq/5/file.ts"
    assert experiments._allowed("https://rr1---sn-abc.googlevideo.com/x")
    assert not experiments._allowed("https://example.com/x")


def test_variants_without_sound_share_the_separate_live_audio():
    video = _fmt("301", height=1080, acodec="none", tbr=4000)
    audio = {**_fmt("234", height=0, vcodec="none", tbr=128), "height": None, "width": None, "language_preference": 10}
    info = {"formats": [video, audio, {**audio, "format_id": "233", "language_preference": -1}]}
    assert experiments.live_audio(info)["format_id"] == "234"
    master = experiments.master_playlist([video], experiments.live_audio(info))
    assert master.splitlines()[3:] == [
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="variant-234.m3u8"',
        '#EXT-X-STREAM-INF:BANDWIDTH=4128000,RESOLUTION=1920x1080,CODECS="avc1.4D401E,mp4a.40.2",AUDIO="audio"',
        "variant-301.m3u8",
    ]
