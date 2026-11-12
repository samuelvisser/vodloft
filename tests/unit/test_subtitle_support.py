from __future__ import annotations

from types import SimpleNamespace

import pytest

from downloader.hls import parse_subtitle_renditions
from downloader.models import MediaKind, SubtitleRendition, VideoRendition
from downloader.plan import ResolvedDownloadSource, SidecarSpec, build_download_plan
from downloader.subtitles import download_hls_webvtt


_MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",NAME="English (Generated)",LANGUAGE="en",URI="subs/en.m3u8",FORCED=NO
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",NAME="French",LANGUAGE="fr",URI="subs/fr.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",NAME="English Forced",LANGUAGE="en",URI="subs/en-forced.m3u8",FORCED=YES
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="other",NAME="Unused",LANGUAGE="de",URI="subs/de.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=1920x1080,SUBTITLES="sub1"
video.m3u8
"""


def test_hls_master_discovers_languages_and_media_server_sidecar_names():
    tracks = parse_subtitle_renditions(_MASTER, "https://cdn.example/master.m3u8?token=secret")

    assert [(track.language, track.forced, track.target_suffix) for track in tracks] == [
        ("en", False, ".en.srt"),
        ("fr", False, ".fr.srt"),
        ("en", True, ".en.forced.srt"),
    ]
    assert tracks[0].url == "https://cdn.example/subs/en.m3u8"


def test_master_probe_preserves_subtitle_renditions(monkeypatch):
    from downloader import downloader

    class Response:
        headers = {"Content-Type": "application/vnd.apple.mpegurl"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return _MASTER.encode()

    monkeypatch.setattr(downloader, "http_get", lambda _url: Response())
    info = downloader.probe("https://cdn.example/master.m3u8")

    assert info.kind is MediaKind.HLS_MASTER
    assert info.subtitles[0].target_suffix == ".en.srt"
    assert len(info.renditions) == 1


def _fake_subtitle_http(monkeypatch, segment_texts: tuple[str, str]):
    import downloader.subtitles as module

    manifest = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:6.0,
segment0.vtt
#EXTINF:6.0,
segment1.vtt
#EXT-X-ENDLIST
"""
    urls = {
        "https://cdn.example/subs.m3u8": manifest.encode(),
        "https://cdn.example/segment0.vtt": segment_texts[0].encode(),
        "https://cdn.example/segment1.vtt": segment_texts[1].encode(),
    }

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


def test_segmented_webvtt_timestamp_maps_produce_synchronized_srt(monkeypatch):
    _fake_subtitle_http(monkeypatch, (
        """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000

00:00:01.000 --> 00:00:02.000
<b>Hello</b>
""",
        """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:1440000

00:00:01.000 --> 00:00:02.000
World
""",
    ))

    result = download_hls_webvtt(
        "https://cdn.example/subs.m3u8",
        maximum_bytes=100000, should_cancel=lambda: False,
    ).srt.decode()

    assert "00:00:01,000 --> 00:00:02,000\nHello" in result
    assert "00:00:07,000 --> 00:00:08,000\nWorld" in result
    assert "X-TIMESTAMP-MAP" not in result
    assert "WEBVTT" not in result


@pytest.mark.parametrize("second_time,expected_time", [
    ("00:00:07.000", "00:00:07,000"),  # already on the media timeline
    ("00:00:01.000", "00:00:07,000"),  # segment-relative fallback
])
def test_webvtt_without_maps_uses_global_or_segment_relative_timing(
    monkeypatch, second_time, expected_time,
):
    _fake_subtitle_http(monkeypatch, (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFirst\n",
        f"WEBVTT\n\n{second_time} --> 00:00:08.000\nSecond\n"
        if second_time.endswith(":07.000")
        else "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nSecond\n",
    ))
    result = download_hls_webvtt(
        "https://cdn.example/subs.m3u8",
        maximum_bytes=100000, should_cancel=lambda: False,
    ).srt.decode()
    assert f"{expected_time} --> 00:00:08,000\nSecond" in result


def test_download_plan_uses_existing_sidecar_and_embedding_stages(tmp_path):
    asset = SidecarSpec(
        "subtitle_0", "subtitle", url="https://cdn.example/subs.m3u8",
        extension="srt", target_suffix=".en.srt", source_format="hls_webvtt",
        language="en", required=False, publish=True,
    )
    plan = build_download_plan(
        source=ResolvedDownloadSource(
            "https://cdn.example/video.m3u8", "1920x1080", True, True, "mp4", False,
        ),
        requested_destination=tmp_path / "Movie.mp4", temporary_root=tmp_path / "temp",
        download_mode="temporary", assets=(asset,),
        subtitle_asset_ids=("subtitle_0",),
    )

    assert plan.stage("embed").code == "embed_subtitles"
    assert "acquire:subtitle_0" in plan.stage("embed").depends_on
    assert "embed" in plan.stage("publish").depends_on
    assert plan.stage("publish:subtitle_0").code == "publish_sidecar"
    assert plan.subtitle_asset_ids == ("subtitle_0",)


def test_movie_profiles_default_to_subtitle_sidecars():
    from backend.api.models.movie_local_media_profile import MovieLocalMediaProfileAPICreate

    movie = MovieLocalMediaProfileAPICreate(
        name="Movie", type="movie", preferred_format="format_1080p",
        output_template="/downloads/movies/{{ movie_title }}/{{ title }}.ext",
    )
    assert movie.subtitle_mode == "sidecar"


@pytest.mark.parametrize(("scope", "expected"), [
    ("both", "sidecar"),
    ("series", "sidecar"),
    ("podcast", "no_subtitles"),
])
def test_collection_subtitle_default_follows_scope_when_not_specified(scope, expected):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    collection = CollectionLocalMediaProfileAPICreate(
        name="Collection", type="collection", collection_scope=scope,
        preferred_format="format_1080p",
        output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
    )
    assert collection.subtitle_mode == expected
    assert collection.model_dump(by_alias=True, mode="json")["subtitle_mode"] == expected


@pytest.mark.parametrize("mode", [
    "no_subtitles", "embed", "sidecar", "embed_and_sidecar",
])
@pytest.mark.parametrize("scope", ["podcast", "series", "both"])
def test_manual_subtitle_selection_overrides_collection_scope(scope, mode):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    profile = CollectionLocalMediaProfileAPICreate(
        name="Collection", preferred_format="format_1080p",
        collection_scope=scope, subtitle_mode=mode,
        output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
    )
    assert profile.subtitle_mode == mode


def test_subtitle_system_mode_is_no_longer_valid():
    from pydantic import ValidationError
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    with pytest.raises(ValidationError):
        CollectionLocalMediaProfileAPICreate(
            name="Collection", preferred_format="format_1080p", subtitle_mode="system",
            output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
        )


def test_system_settings_no_longer_expose_subtitle_mode():
    from backend.api.models.settings import SettingsValues
    from config.settings.settings import AppSettings

    settings = AppSettings()
    assert "subtitle_mode" not in type(settings.download_settings).model_fields
    serialized = SettingsValues.from_app_settings(settings).model_dump(
        by_alias=True, mode="json",
    )
    assert "subtitleMode" not in serialized["downloadSettings"]


def test_subtitle_mp4_embedding_uses_mov_text_and_three_letter_language(tmp_path, monkeypatch):
    from downloader import ffmpeg as ffmpeg_module

    media = tmp_path / "Movie.mp4"
    srt = tmp_path / "Movie.en.srt"
    media.write_bytes(b"media")
    srt.write_text("1\n00:00:00,100 --> 00:00:01,000\nHello\n")
    commands = []

    monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    def run(command, **_kwargs):
        commands.append(command)
        with open(command[-1], "wb") as out:
            out.write(b"embedded")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", run)
    ffmpeg_module.embed_media(str(media), subtitles=(("en", str(srt), False, None),))

    assert media.read_bytes() == b"embedded"
    assert "-c:s" in commands[0]
    assert commands[0][commands[0].index("-c:s") + 1] == "mov_text"
    assert "language=eng" in commands[0]
    assert "1:s:0" in commands[0]
    # Subtitle tracks already in the media are replaced, so labels line up.
    assert "-0:s?" in commands[0]


@pytest.mark.parametrize("publish,embed", [
    (True, False),
    (False, True),
    (True, True),
])
def test_subtitles_use_existing_publication_and_embedding_lifecycle(
    tmp_path, monkeypatch, publish, embed,
):
    from pathlib import Path

    from downloader import coordinator, sidecars
    from downloader.capacity import DownloadResources
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadProgress, DownloadResult

    from downloader.subtitles import DownloadedSubtitle

    payload = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
    webvtt = b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n"
    monkeypatch.setattr(sidecars, "download_hls_webvtt", lambda *_args, **_kwargs: DownloadedSubtitle(payload, webvtt))
    embedding_calls = []
    monkeypatch.setattr(
        coordinator, "embed_media",
        lambda *args, **kwargs: embedding_calls.append(kwargs),
    )

    def transfer(_url, destination, *, progress, should_cancel):
        Path(destination).write_bytes(b"media")
        progress(DownloadProgress(5, 5))
        return DownloadResult(destination, 5)

    monkeypatch.setattr(coordinator, "download_file", transfer)
    asset = SidecarSpec(
        "subtitle_0", "subtitle", url="https://cdn.example/subs.m3u8",
        source_format="hls_webvtt", extension="srt", language="en",
        target_suffix=".en.srt", publish=publish, required=False,
    )
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=ResolvedDownloadSource(
                "https://cdn.example/Movie.mp4", "1080p", False, False, "mp4", False,
            ),
            requested_destination=tmp_path / "library" / "Movie.mp4",
            temporary_root=tmp_path / "temp", download_mode="temporary",
            assets=(asset,),
            subtitle_asset_ids=("subtitle_0",) if embed else (),
            attempt_id=tracker.attempt_id,
        )
        execution = coordinator.execute_download_plan(
            plan, tracker=tracker, resources=DownloadResources(),
        )
        assert Path(execution.result.path).read_bytes() == b"media"
        if publish:
            assert (tmp_path / "library" / "Movie.en.srt").read_bytes() == payload
            assert execution.assets[0].kind == "subtitle"
        else:
            assert not (tmp_path / "library" / "Movie.en.srt").exists()
            assert not execution.assets
        if embed:
            assert len(embedding_calls) == 1
            assert embedding_calls[0]["subtitles"] == (
                ("en", embedding_calls[0]["subtitles"][0][1], False, None),
            )
            assert Path(embedding_calls[0]["subtitles"][0][1]).is_file()
        else:
            assert embedding_calls == []
        execution.cleanup_workspace()


def test_unavailable_optional_subtitles_do_not_fail_media_download(tmp_path, monkeypatch):
    from pathlib import Path

    from downloader import coordinator, sidecars
    from downloader.capacity import DownloadResources
    from downloader.errors import DownloadError
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadProgress, DownloadResult

    def missing(*_args, **_kwargs):
        raise DownloadError("Subtitle stream unavailable")

    monkeypatch.setattr(sidecars, "download_hls_webvtt", missing)

    def transfer(_url, path, *, progress, should_cancel):
        Path(path).write_bytes(b"media")
        progress(DownloadProgress(5, 5))
        return DownloadResult(path, 5)

    monkeypatch.setattr(coordinator, "download_file", transfer)
    asset = SidecarSpec(
        "subtitle_0", "subtitle", url="https://cdn.example/subs.m3u8",
        source_format="hls_webvtt", extension="srt", language="en",
        target_suffix=".en.srt", attempts=1, required=False,
    )
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=ResolvedDownloadSource(
                "https://cdn.example/Movie.mp4", "1080p", False, False, "mp4", False,
            ),
            requested_destination=tmp_path / "library" / "Movie.mp4",
            temporary_root=tmp_path / "temp", download_mode="temporary",
            assets=(asset,), attempt_id=tracker.attempt_id,
        )
        execution = coordinator.execute_download_plan(
            plan, tracker=tracker, resources=DownloadResources(),
        )
        assert Path(execution.result.path).read_bytes() == b"media"
        assert execution.assets == ()
        assert not (tmp_path / "library" / "Movie.en.srt").exists()
        execution.cleanup_workspace()


@pytest.mark.parametrize(("subtitles", "embed"), [
    ((("en", "Hello"), ("nl", "Hallo")), False),
    ((("en", "Hello"), ("nl", "Hallo")), True),
    ((), True),
])
def test_ytdlp_subtitles_publish_one_sidecar_per_language(tmp_path, monkeypatch, subtitles, embed):
    from pathlib import Path

    from downloader import coordinator
    from downloader.capacity import DownloadResources
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadProgress, DownloadResult, WrittenSubtitle

    embedding_calls = []
    monkeypatch.setattr(coordinator, "embed_media", lambda *args, **kwargs: embedding_calls.append(kwargs))

    def transfer(_url, destination, *, command, subtitles_dir, progress, should_cancel, **_options):
        assert subtitles_dir is not None
        Path(destination).write_bytes(b"media")
        written = []
        for language, text in subtitles:
            path = subtitles_dir / f"ytdlp-subtitle.{language}.srt"
            path.write_text(f"1\n00:00:01,000 --> 00:00:02,000\n{text}\n\n")
            written.append(WrittenSubtitle(language, str(path)))
        progress(DownloadProgress(5, 5))
        return DownloadResult(destination, 5, subtitles=tuple(written))

    monkeypatch.setattr(coordinator, "download_ytdlp", transfer)
    asset = SidecarSpec(
        "subtitles", "subtitle", url="https://www.youtube.com/watch?v=x", extension="srt",
        source_format="ytdlp", publish=True, required=False,
    )
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=ResolvedDownloadSource(
                "https://www.youtube.com/watch?v=x", "up to 1080p", False, False, "mp4", False,
                ytdlp_command=("yt-dlp",),
            ),
            requested_destination=tmp_path / "library" / "Video.mp4",
            temporary_root=tmp_path / "temp", download_mode="temporary",
            assets=(asset,), subtitle_asset_ids=("subtitles",) if embed else (),
            attempt_id=tracker.attempt_id,
        )
        execution = coordinator.execute_download_plan(plan, tracker=tracker, resources=DownloadResources())
        library = tmp_path / "library"
        assert sorted(path.name for path in library.iterdir()) == sorted(
            ["Video.mp4", *(f"Video.{language}.srt" for language, _ in subtitles)]
        )
        assert sorted(item.id for item in execution.assets) == sorted(f"subtitles-{language}" for language, _ in subtitles)
        assert {item.kind for item in execution.assets} <= {"subtitle"}
        if embed and subtitles:
            assert [item[0] for item in embedding_calls[0]["subtitles"]] == ["en", "nl"]
        elif embed:
            assert embedding_calls == [] or embedding_calls[0]["subtitles"] == ()
        assert not tracker.snapshot().warnings
        execution.cleanup_workspace()


def test_ytdlp_subtitles_need_a_ytdlp_download(tmp_path):
    asset = SidecarSpec(
        "subtitles", "subtitle", url="https://www.youtube.com/watch?v=x", extension="srt",
        source_format="ytdlp", required=False,
    )
    with pytest.raises(ValueError, match="yt-dlp download"):
        build_download_plan(
            source=ResolvedDownloadSource("https://cdn.example/a.mp4", "1080p", False, False, "mp4", False),
            requested_destination=tmp_path / "a.mp4", temporary_root=tmp_path / "t",
            download_mode="temporary", assets=(asset,),
        )


@pytest.mark.parametrize(("languages", "files", "default_index"), [
    (("nl", "en"), ["Video.en.srt", "Video.nl.default.srt"], 1),
    (("fr", "en-US"), ["Video.en.default.srt", "Video.nl.srt"], 0),
    (("fr",), ["Video.en.srt", "Video.nl.srt"], None),
    ((), ["Video.en.srt", "Video.nl.srt"], None),
])
def test_the_default_subtitle_is_marked_inside_and_beside_the_media(tmp_path, monkeypatch, languages, files, default_index):
    from pathlib import Path

    from downloader import coordinator
    from downloader.capacity import DownloadResources
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadProgress, DownloadResult, WrittenSubtitle

    embedding_calls = []
    monkeypatch.setattr(coordinator, "embed_media", lambda *args, **kwargs: embedding_calls.append(kwargs))

    def transfer(_url, destination, *, command, subtitles_dir, progress, should_cancel, **_options):
        Path(destination).write_bytes(b"media")
        written = []
        for language in ("en", "nl"):
            path = subtitles_dir / f"ytdlp-subtitle.{language}.srt"
            path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
            written.append(WrittenSubtitle(language, str(path)))
        progress(DownloadProgress(5, 5))
        return DownloadResult(destination, 5, subtitles=tuple(written))

    monkeypatch.setattr(coordinator, "download_ytdlp", transfer)
    asset = SidecarSpec(
        "subtitles", "subtitle", url="https://www.youtube.com/watch?v=x", extension="srt",
        source_format="ytdlp", publish=True, required=False,
    )
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=ResolvedDownloadSource(
                "https://www.youtube.com/watch?v=x", "up to 1080p", False, False, "mp4", False,
                ytdlp_command=("yt-dlp",),
            ),
            requested_destination=tmp_path / "library" / "Video.mp4",
            temporary_root=tmp_path / "temp", download_mode="temporary",
            assets=(asset,), subtitle_asset_ids=("subtitles",),
            default_subtitle_languages=languages, attempt_id=tracker.attempt_id,
        )
        execution = coordinator.execute_download_plan(plan, tracker=tracker, resources=DownloadResources())
        assert sorted(path.name for path in (tmp_path / "library").iterdir()) == sorted(["Video.mp4", *files])
        assert embedding_calls[0]["default_subtitle"] == default_index
        execution.cleanup_workspace()


def test_a_forced_subtitle_is_never_the_default():
    from pathlib import Path

    from downloader.sidecars import AcquiredSidecar, default_subtitle

    def acquired(language, forced=False):
        spec = SidecarSpec(f"s-{language}-{int(forced)}", "subtitle", url="https://a/s", extension="srt", language=language, forced=forced)
        return AcquiredSidecar(spec, Path("s.srt"), f".{language}{'.forced' if forced else ''}.srt", 1)

    forced, english = acquired("en", forced=True), acquired("en")
    assert default_subtitle([forced, english], ("en",)) is english
    assert default_subtitle([forced], ("en",)) is None


def test_adoption_finds_the_default_subtitle_beside_the_media():
    from backend.services.adoption import _SUBTITLE

    assert _SUBTITLE.match(".en.default.srt").group("language") == "en"
