"""Embedded subtitles of an HLS bundle are WebVTT files inside the bundle, listed in its playlist;
subtitles beside it are SRT files the bundle does not refer to."""
from __future__ import annotations

from pathlib import Path

import pytest

from downloader.plan import ResolvedDownloadSource, SidecarSpec, build_download_plan
from downloader.subtitles import download_hls_webvtt, srt_to_webvtt


def _fake_subtitle_http(monkeypatch, segments: dict[str, str]):
    import downloader.subtitles as module

    manifest = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n" + "".join(
        f"#EXTINF:6.0,\n{name}\n" for name in segments
    ) + "#EXT-X-ENDLIST\n"
    urls = {"https://cdn.example/subs.m3u8": manifest.encode()}
    urls.update({f"https://cdn.example/{name}": text.encode() for name, text in segments.items()})

    class Response:
        def __init__(self, data: bytes):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_chunks(self, _chunk_size):
            yield self.data

    monkeypatch.setattr(module, "http_get", lambda url: Response(urls[url]))


def test_segmented_webvtt_becomes_one_document_on_the_first_segments_timeline(monkeypatch):
    _fake_subtitle_http(monkeypatch, {
        "segment0.vtt": "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n"
                        "00:00:01.000 --> 00:00:02.000 line:90% align:start\n<b>Hello</b>\n",
        "segment1.vtt": "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:1440000\n\n"
                        "00:00:01.000 --> 00:00:02.000\n<i>World</i>\n",
    })

    webvtt = download_hls_webvtt(
        "https://cdn.example/subs.m3u8", maximum_bytes=100000, should_cancel=lambda: False,
    ).webvtt.decode()

    # The first segment's map lines the whole document up with the video, as it did each segment;
    # the source's own cue settings and tags are kept.
    assert webvtt == (
        "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n"
        "\n00:00:01.000 --> 00:00:02.000 line:90% align:start\n<b>Hello</b>\n"
        "\n00:00:07.000 --> 00:00:08.000\n<i>World</i>\n"
    )


def test_srt_becomes_webvtt():
    srt = "﻿1\r\n00:00:01,000 --> 00:00:02,500\r\nHello\r\nthere\r\n\r\n2\r\n00:01:00,000 --> 00:01:01,000\r\n<i>Bye</i>\r\n"
    assert srt_to_webvtt(srt).decode() == (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello\nthere\n\n00:01:00.000 --> 00:01:01.000\n<i>Bye</i>\n"
    )


def _bundle(tmp_path) -> Path:
    from downloader import hls_asset_marker, hls_asset_root

    master = tmp_path / "episode.m3u8"
    master.write_text(
        "#EXTM3U\n#EXT-X-VERSION:7\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="hls/audio-0/playlist.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="audio"\nhls/360p/playlist.m3u8\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2,AUDIO="audio"\nhls/720p/playlist.m3u8\n'
    )
    root = hls_asset_root(master)
    root.mkdir()
    hls_asset_marker(master).write_text("owned")
    for name in ("audio-0", "360p", "720p"):
        (root / name).mkdir()
        (root / name / "media.mp4").write_bytes(b"x")
        (root / name / "playlist.m3u8").write_text("#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\nmedia.mp4\n#EXTINF:4.5,\nmedia.mp4\n#EXT-X-ENDLIST\n")
    return master


def test_subtitles_are_kept_in_the_bundle_and_listed_with_each_resolution(tmp_path):
    from downloader import hls_asset_root, missing_hls_bundle_files
    from downloader.hls_bundle import BundleSubtitle, add_hls_subtitles

    master = _bundle(tmp_path)
    english, forced = tmp_path / "en.vtt", tmp_path / "en-forced.vtt"
    english.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n")
    forced.write_text("WEBVTT\n\n00:00:03.000 --> 00:00:04.000\nHola\n")

    add_hls_subtitles(master, [
        BundleSubtitle(english, "en", "en", default=True),
        BundleSubtitle(forced, "en", "en (forced)", forced=True),
    ])

    lines = master.read_text().splitlines()
    assert lines[3:5] == [
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",NAME="en",LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,'
        'URI="hls/subtitles-0/playlist.m3u8"',
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",NAME="en (forced)",LANGUAGE="en",DEFAULT=NO,AUTOSELECT=YES,FORCED=YES,'
        'URI="hls/subtitles-1/playlist.m3u8"',
    ]
    assert [line for line in lines if line.startswith("#EXT-X-STREAM-INF:")] == [
        '#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="audio",SUBTITLES="subtitles"',
        '#EXT-X-STREAM-INF:BANDWIDTH=2,AUDIO="audio",SUBTITLES="subtitles"',
    ]
    root = hls_asset_root(master)
    # Parts as long as the video's, each with the cues it shows.
    assert (root / "subtitles-1" / "playlist.m3u8").read_text() == (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:6.000,\n0.vtt\n#EXTINF:4.500,\n1.vtt\n#EXT-X-ENDLIST\n"
    )
    assert (root / "subtitles-0" / "0.vtt").read_text() == english.read_text()
    assert (root / "subtitles-0" / "1.vtt").read_text() == "WEBVTT\n"
    assert missing_hls_bundle_files(master) == []

    # The bundle needs its subtitles, just like its video.
    (root / "subtitles-1" / "1.vtt").unlink()
    assert missing_hls_bundle_files(master) == [(root / "subtitles-1" / "1.vtt").resolve()]


def test_a_cue_that_crosses_into_the_next_part_is_in_both(tmp_path):
    from downloader.hls_bundle import write_hls_subtitle_segments

    write_hls_subtitle_segments(
        "\ufeffWEBVTT\r\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\r\n\r\nSTYLE\r\n::cue { color: lime }\r\n\r\n"
        "NOTE left out\r\n\r\n1\r\n00:05.000 --> 00:07.000 align:start\r\nAcross\r\n\r\n"
        "00:00:13.000 --> 00:00:14.000\r\nLast\r\n",
        tmp_path, duration=14.0, segment_seconds=6,
    )

    header = "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\nSTYLE\n::cue { color: lime }"
    across = "1\n00:05.000 --> 00:07.000 align:start\nAcross"
    assert [(tmp_path / f"{number}.vtt").read_text() for number in range(3)] == [
        f"{header}\n\n{across}\n", f"{header}\n\n{across}\n", f"{header}\n\n00:00:13.000 --> 00:00:14.000\nLast\n",
    ]
    assert "#EXTINF:2.000,\n2.vtt\n#EXT-X-ENDLIST" in (tmp_path / "playlist.m3u8").read_text()


def test_whole_video_subtitles_of_earlier_downloads_are_split(tmp_path):
    import importlib

    from downloader import hls_asset_root, missing_hls_bundle_files

    migration = importlib.import_module(
        "backend.db.background_migrations.versions.875ce72375ca_split_hls_bundle_subtitles"
    )
    master = _bundle(tmp_path)
    root = hls_asset_root(master)
    (root / "subtitles-0").mkdir()
    (root / "subtitles-0" / "subtitles.vtt").write_text("WEBVTT\n\n00:00:07.000 --> 00:00:08.000\nLater\n")
    (root / "subtitles-0" / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:11\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:10.500,\nsubtitles.vtt\n#EXT-X-ENDLIST\n"
    )
    master.write_text(master.read_text().replace(
        "#EXT-X-STREAM-INF:BANDWIDTH=1,", '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",NAME="en",URI="hls/subtitles-0/playlist.m3u8"\n'
        "#EXT-X-STREAM-INF:BANDWIDTH=1,",
    ))

    assert migration._split(str(master)) == 1
    assert not (root / "subtitles-0" / "subtitles.vtt").exists()
    assert (root / "subtitles-0" / "0.vtt").read_text() == "WEBVTT\n"
    assert (root / "subtitles-0" / "1.vtt").read_text() == "WEBVTT\n\n00:00:07.000 --> 00:00:08.000\nLater\n"
    assert missing_hls_bundle_files(master) == []
    # Split once.
    assert migration._split(str(master)) == 0


@pytest.mark.parametrize(("publish", "embed"), [(True, False), (False, True), (True, True)])
def test_a_daily_wire_hls_bundle_keeps_embedded_subtitles_inside_and_sidecars_beside_it(tmp_path, monkeypatch, publish, embed):
    import shutil

    from downloader import coordinator, hls_asset_root, missing_hls_bundle_files, sidecars
    from downloader.capacity import DownloadResources
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadProgress, DownloadResult
    from downloader.subtitles import DownloadedSubtitle

    srt = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
    webvtt = b"WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n00:00:01.000 --> 00:00:02.000\nHello\n"
    parts = (
        (6.0, b"WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n00:00:01.000 --> 00:00:02.000\nHello\n"),
        (4.5, b"WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:1440000\n\n"),
    )
    monkeypatch.setattr(sidecars, "download_hls_webvtt", lambda *_args, **_kwargs: DownloadedSubtitle(srt, webvtt, parts))
    monkeypatch.setattr(coordinator, "embed_media", lambda *_args, **_kwargs: pytest.fail("A bundle is not embedded into"))
    (tmp_path / "source").mkdir()
    made = _bundle(tmp_path / "source")

    def transfer(_url, destination, *, progress, should_cancel):
        shutil.copyfile(made, destination)
        shutil.copytree(hls_asset_root(made), hls_asset_root(destination))
        progress(DownloadProgress(5, 5))
        return DownloadResult(destination, 5)

    monkeypatch.setattr(coordinator, "download_hls_bundle", transfer)
    asset = SidecarSpec(
        "subtitle_0", "subtitle", url="https://cdn.example/subs.m3u8", source_format="hls_webvtt", extension="srt",
        language="en", target_suffix=".en.srt", publish=publish, required=False,
    )
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=ResolvedDownloadSource("https://cdn.example/master.m3u8", "HLS", False, False, "m3u8", False, hls_bundle=True),
            requested_destination=tmp_path / "library" / "Episode.m3u8",
            temporary_root=tmp_path / "temp", download_mode="temporary",
            assets=(asset,), subtitle_asset_ids=("subtitle_0",) if embed else (),
            default_subtitle_languages=("en",), attempt_id=tracker.attempt_id,
        )
        execution = coordinator.execute_download_plan(plan, tracker=tracker, resources=DownloadResources())
        library = tmp_path / "library"
        master = library / "Episode.m3u8"
        assert execution.result.path == str(master) and missing_hls_bundle_files(master) == []
        bundled = hls_asset_root(master) / "subtitles-0" / "0.vtt"
        if embed:
            # The source's own WebVTT parts, as they are.
            assert [bundled.read_bytes(), bundled.with_name("1.vtt").read_bytes()] == [data for _, data in parts]
            assert "#EXTINF:6.000,\n0.vtt\n#EXTINF:4.500,\n1.vtt\n" in bundled.with_name("playlist.m3u8").read_text()
            assert 'SUBTITLES="subtitles"' in master.read_text() and 'NAME="en",LANGUAGE="en",DEFAULT=YES' in master.read_text()
        else:
            assert not bundled.exists() and "SUBTITLES" not in master.read_text()
        sidecar = library / "Episode.en.default.srt"
        assert sidecar.is_file() == publish
        if publish:
            assert sidecar.read_bytes() == srt
            # The bundle does not need the file beside it.
            sidecar.unlink()
            assert missing_hls_bundle_files(master) == []
        assert not tracker.snapshot().warnings
        execution.cleanup_workspace()


def test_hls_bundles_still_take_no_embedded_metadata(tmp_path):
    from downloader.errors import DownloadError

    with pytest.raises(DownloadError, match="not embedded artwork or metadata"):
        build_download_plan(
            source=ResolvedDownloadSource("https://cdn.example/master.m3u8", "HLS", False, False, "m3u8", False, hls_bundle=True),
            requested_destination=tmp_path / "Episode.m3u8", temporary_root=tmp_path / "temp", download_mode="temporary",
            metadata_tags=(("title", "x"),), attempt_id="a",
        )


def test_ytdlp_subtitles_for_a_bundle_are_kept_as_webvtt_too(tmp_path):
    from downloader.plan import YtdlpSubtitles
    from downloader.ytdlp import _keep_subtitles, ytdlp_subtitle_options

    options = ytdlp_subtitle_options(YtdlpSubtitles(), webvtt=True)
    # A site's own WebVTT is taken first.
    assert options[options.index("--sub-format") + 1] == "vtt/srt/best"
    work, target = tmp_path / "work", tmp_path / "keep"
    work.mkdir()
    target.mkdir()
    vtt = "WEBVTT\nKind: captions\n\n00:00:01.000 --> 00:00:02.000 align:start\n<c>Hello</c>\n"
    (work / "media.en.vtt").write_text(vtt)
    (work / "media.nl.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHallo\n\n")

    kept = {item.language: item for item in _keep_subtitles(work, target, YtdlpSubtitles(), webvtt=True)}

    assert Path(kept["en"].webvtt_path).read_text() == vtt
    assert Path(kept["en"].path).read_text() == "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
    assert Path(kept["nl"].webvtt_path).read_text() == "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHallo\n"
    # Without a bundle only SRT is written.
    other = tmp_path / "other"
    other.mkdir()
    assert all(item.webvtt_path is None for item in _keep_subtitles(work, other, YtdlpSubtitles()))
    assert not list(other.glob("*.vtt"))
