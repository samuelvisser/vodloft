"""A YouTube video downloads as an HLS bundle: each resolution and the audio as yt-dlp downloads them,
split into parts by ffmpeg without encoding them again."""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

# Writes a small H.264 video per requested resolution and an AAC audio, as YouTube has them.
FAKE_YTDLP = textwrap.dedent('''
    import pathlib, subprocess, sys
    args = sys.argv[1:]
    work = pathlib.Path(args[args.index("-P") + 1])
    selectors = args[args.index("-f") + 1].split(",")
    track = next(value for value in args[args.index("--print") + 1:] if "[vodloft-track]" in value).removeprefix("after_move:")
    template = args[args.index("--progress-template") + 1].removeprefix("download:")
    # The video has 360p and 720p; the 1080p selector takes the 720p again.
    formats = {360: ("134", 640, 360, 300), 720: ("136", 1280, 720, 1200), 1080: ("136", 1280, 720, 1200)}
    for selector in selectors:
        if selector.startswith("bv"):
            height = int(selector.split("<=")[1].split("]")[0])
            format_id, width, real, tbr = formats[height]
            path = work / f"track-{format_id}.mp4"
            if not path.exists():
                subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={width}x{real}:rate=25",
                                "-t", "14", "-c:v", "libx264", "-g", "50", "-an", str(path)], check=True)
            values = dict(format_id=format_id, width=width, height=real, vcodec="avc1.4d401f", acodec="none", tbr=tbr, abr="NA")
        else:
            path = work / "track-140.m4a"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "14",
                            "-c:a", "aac", str(path)], check=True)
            values = dict(format_id="140", width="NA", height="NA", vcodec="none", acodec="mp4a.40.2", tbr="NA", abr=129)
        size = path.stat().st_size
        print(template.replace("%(progress.downloaded_bytes)s", str(size)).replace("%(progress.total_bytes)s", str(size))
              .replace("%(progress.total_bytes_estimate)s", "NA"))
        line = track
        for key, value in {**values, "filepath": str(path)}.items():
            line = line.replace(f"%({key})s", str(value))
        print(line)
''')


def _part_header(playlist):
    """The header the parts of an HLS playlist share."""
    byte_range = playlist.read_text().split('BYTERANGE="', 1)[1].split('"', 1)[0]
    length, offset = (int(value) for value in byte_range.split("@"))
    with (playlist.parent / "media.mp4").open("rb") as media:
        media.seek(offset)
        return media.read(length)


@pytest.fixture
def fake_ytdlp(tmp_path):
    script = tmp_path / "fake_ytdlp.py"
    script.write_text(FAKE_YTDLP)
    return (sys.executable, str(script))


def test_a_youtube_video_downloads_as_an_hls_bundle(fake_ytdlp, tmp_path):
    from downloader import missing_hls_bundle_files
    from downloader.ytdlp import download_ytdlp_hls_bundle, resolve_ytdlp_source

    source = resolve_ytdlp_source("https://x/video", command=fake_ytdlp, preferred_format="format_hls", audio_only=False)
    assert (source.extension, source.hls_bundle, source.format_downloaded) == ("m3u8", True, "HLS 360p/720p/1080p")
    master = tmp_path / "episode.m3u8"
    seen = []
    result = download_ytdlp_hls_bundle("https://x/video", str(master), command=source.ytdlp_command, progress=seen.append)

    assert result.path == str(master) and result.bytes_downloaded > 0 and seen
    lines = master.read_text().splitlines()
    assert '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="hls/audio-0/playlist.m3u8"' in lines
    # One variant per resolution the video has, from the lowest up.
    assert [line for line in lines if not line.startswith("#")] == ["hls/360p/playlist.m3u8", "hls/720p/playlist.m3u8"]
    assert '#EXT-X-STREAM-INF:BANDWIDTH=1329000,CODECS="avc1.4d401f,mp4a.40.2",RESOLUTION=1280x720,AUDIO="audio"' in lines
    playlist = (tmp_path / "episode.m3u8.assets" / "720p" / "playlist.m3u8").read_text()
    assert '#EXT-X-MAP:URI="media.mp4",BYTERANGE=' in playlist and "#EXT-X-BYTERANGE:" in playlist
    assert missing_hls_bundle_files(master) == []
    assert not (tmp_path / "episode.m3u8.ytdlp").exists()

    # The parts play: ffmpeg reads each track back from its playlist. Their header has no edit list,
    # which Apple's players would show no picture with.
    for name in ("360p", "720p", "audio-0"):
        assert b"edts" not in _part_header(tmp_path / "episode.m3u8.assets" / name / "playlist.m3u8")
        probe = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(tmp_path / "episode.m3u8.assets" / name / "playlist.m3u8"), "-f", "null", "-"],
            capture_output=True, text=True,
        )
        assert probe.returncode == 0, probe.stderr


def test_an_hls_bundle_misses_a_listed_resolution(tmp_path):
    from downloader import hls_asset_marker, hls_asset_root, missing_hls_bundle_files

    master = tmp_path / "episode.m3u8"
    master.write_text("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhls/360p/playlist.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2\nhls/720p/playlist.m3u8\n")
    hls_asset_root(master).mkdir()
    hls_asset_marker(master).write_text("owned")
    (hls_asset_root(master) / "360p").mkdir()
    (hls_asset_root(master) / "360p" / "media.mp4").write_bytes(b"x")
    (hls_asset_root(master) / "360p" / "playlist.m3u8").write_text("#EXTM3U\n#EXTINF:6,\nmedia.mp4\n")
    assert missing_hls_bundle_files(master) == [hls_asset_root(master) / "720p" / "playlist.m3u8"]
    # A master that lists no video is no bundle at all.
    master.write_text("#EXTM3U\n")
    assert missing_hls_bundle_files(master) == [master]


def test_an_hls_bundle_only_marks_sponsorblock_segments():
    from downloader.plan import YtdlpSponsorBlock
    from downloader.ytdlp import resolve_ytdlp_source

    source = resolve_ytdlp_source(
        "https://x", command=("yt-dlp",), preferred_format="format_hls", audio_only=False,
        sponsorblock=YtdlpSponsorBlock(chapter=("intro",), cut=("sponsor",)),
    )
    assert "--sponsorblock-remove" not in source.ytdlp_command
    assert source.ytdlp_command[source.ytdlp_command.index("--sponsorblock-mark") + 1] == "intro,sponsor"
