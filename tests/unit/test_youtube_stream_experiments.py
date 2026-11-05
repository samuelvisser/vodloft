"""EXPERIMENT: the YouTube video streaming methods pick the right formats and write valid HLS playlists."""
from __future__ import annotations

from backend.api.endpoints.feeds import youtube_experiments as experiments


def _fmt(format_id, *, vcodec="none", acodec="none", protocol="https", ext="mp4", height=None, tbr=None, **extra):
    return {
        "format_id": format_id, "vcodec": vcodec, "acodec": acodec, "protocol": protocol, "ext": ext,
        "height": height, "tbr": tbr, "url": f"https://rr1.googlevideo.com/videoplayback?itag={format_id}", **extra,
    }


INFO = {"formats": [
    _fmt("18", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360),
    _fmt("137", vcodec="avc1.640028", height=1080, width=1920, tbr=4000),
    _fmt("136", vcodec="avc1.4d401f", height=720),
    _fmt("248", vcodec="vp9", ext="webm", height=1080),
    _fmt("299", vcodec="avc1.64002a", height=1080, protocol="m3u8_native"),
    _fmt("140-0", acodec="mp4a.40.2", ext="m4a", language_preference=-1),
    _fmt("140-1", acodec="mp4a.40.2", ext="m4a", language_preference=10),
    _fmt("140-drc", acodec="mp4a.40.2", ext="m4a", language_preference=10),
]}


def _box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def _sidx(fragments: list[tuple[int, int]], timescale: int = 1000) -> bytes:
    body = bytes(4) + (1).to_bytes(4, "big") + timescale.to_bytes(4, "big") + bytes(4) + bytes(4)
    body += bytes(2) + len(fragments).to_bytes(2, "big")
    for size, duration in fragments:
        body += size.to_bytes(4, "big") + duration.to_bytes(4, "big") + (0x90000000).to_bytes(4, "big")
    return _box(b"sidx", body)


def test_the_1080p_methods_join_h264_video_with_the_original_audio():
    assert experiments._format_18(INFO)["format_id"] == "18"
    assert experiments._video_1080(INFO)["format_id"] == "137"
    assert experiments._audio_m4a(INFO)["format_id"] == "140-1"


def test_the_segment_index_of_a_youtube_file_gives_every_part():
    head = _box(b"ftyp", b"dash" + bytes(4)) + _box(b"moov", bytes(20))
    data = head + _sidx([(1000, 5000), (2000, 4500)]) + _box(b"moof", bytes(8))
    init_size, fragments = experiments.parse_index(data)
    assert init_size == len(head)
    first = len(head) + len(_sidx([(0, 0), (0, 0)]))
    assert fragments == [(first, 1000, 5.0), (first + 1000, 2000, 4.5)]
    assert experiments.parse_index(data[:len(head) + 10]) is None


def test_hls_playlists_list_every_part_as_a_byte_range():
    playlist = experiments.media_playlist("part/137", 785, [(1065, 100, 5.0), (1165, 200, 4.5)]).splitlines()
    assert playlist[5] == '#EXT-X-MAP:URI="part/137",BYTERANGE="785@0"'
    assert playlist[6:9] == ["#EXTINF:5.000,", "#EXT-X-BYTERANGE:100@1065", "part/137"]
    assert playlist[-1] == "#EXT-X-ENDLIST"
    master = experiments.master_playlist(experiments._video_1080(INFO), experiments._audio_m4a(INFO))
    assert 'CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1920x1080,AUDIO="audio"' in master
