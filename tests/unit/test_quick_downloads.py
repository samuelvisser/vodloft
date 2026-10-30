"""Quick downloads: one file fetched for the browser, never added to the library."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sources import (
    EpisodeMedia, Feature, LinkKind, Playback, PlaybackKind, ResolvedLink, Source, VideoDetails, VideoFormat, VideoFormats,
    registry,
)


class ClipSource(Source):
    id = "clips"
    name = "Clips"
    domains = ("clips.example",)
    features = frozenset({Feature.VIDEOS})

    def resolve(self, url):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        kind = LinkKind.SHOW if slug.startswith("channel") else LinkKind.VIDEO
        return ResolvedLink(
            kind=kind, slug=slug, url=url, title=f"Clip: {slug}?", image_url="https://img.clips.example/a.jpg",
            author_name="A Channel", drm_protected=slug.startswith("locked"),
        )

    def video_details(self, url):
        return VideoDetails(slug="abc", url=url, title="Clip", author_name="A Channel", duration=61.0)

    def video_playback(self, *, slug, url):
        if slug.startswith("late-lock"):
            return Playback(url="https://cdn.clips.example/x.m3u8", drm_protected=True)
        return Playback(url=f"https://cdn.clips.example/{slug}.m3u8")


class TubeSource(ClipSource):
    id = "tube"
    name = "Tube"
    domains = ("tube.example",)
    features = frozenset({Feature.VIDEOS, Feature.FORMAT_CHOICES})

    def video_playback(self, *, slug, url):
        return Playback(url=url, kind=PlaybackKind.YTDLP, command=("yt-dlp",))

    def video_formats(self, url):
        return VideoFormats(videos=(
            VideoFormat(2160, "vp9", 900), VideoFormat(2160, "av1", 700),
            VideoFormat(1080, "h264", 300), VideoFormat(1080, "vp9", 200), VideoFormat(1080, "av1", None),
            VideoFormat(1088, "h264", 310), VideoFormat(360, "h264", 20),
        ), audio_size_bytes=50, duration=100.0)


class WireSource(ClipSource):
    id = "wire"
    name = "Wire"
    domains = ("wire.example",)
    features = frozenset({Feature.SHOWS, Feature.MOVIES})

    def __init__(self):
        self.media_requests: list[bool] = []

    def resolve(self, url):
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return ResolvedLink(kind=LinkKind.EPISODE, slug=slug, url=url, title=f"Episode {slug}")

    def episode_media(self, *, slug, members_only, interactive=False):
        self.media_requests.append(members_only)
        if slug == "members" and not members_only:
            return EpisodeMedia(video_url=None, audio_url=None)
        return EpisodeMedia(video_url="https://cdn.wire.example/v.m3u8", audio_url=None)


@pytest.fixture
def quick_sources(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return SimpleNamespace(
        clips=registry.register(ClipSource()), tube=registry.register(TubeSource()),
        wire=registry.register(WireSource()),
    )


@pytest.fixture
def temporary_root(tmp_path, monkeypatch):
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.download_settings, "temporary_download_root", tmp_path / "temporary")
    monkeypatch.setattr(settings.quick_download, "keep_free_gigabytes", 0)
    # The history has its own tests, with its table.
    monkeypatch.setattr(settings.quick_download, "keep_history", False)
    return tmp_path / "temporary"


def _request(source_key="clips", slug="abc", link_kind=LinkKind.VIDEO, **choice):
    from backend.services.quick_downloads import QuickChoice, QuickDownloadRequest
    from downloader.storage.quick import new_quick_download_id

    return QuickDownloadRequest(
        id=new_quick_download_id(), source_key=source_key, kind=link_kind, slug=slug,
        url=f"https://{source_key}.example/v/{slug}", title="Clip: abc?", image_url="https://img.clips.example/a.jpg",
        author_name="A Channel", choice=QuickChoice(**choice),
    )


def _probe(monkeypatch, extension="mp4"):
    from backend.services import quick_downloads
    from downloader.plan import ResolvedDownloadSource

    probed = {}

    def resolve_download_source(url, **kwargs):
        probed.update(url=url, **kwargs)
        audio = kwargs["audio_only"]
        return ResolvedDownloadSource(
            url=url, format_downloaded="audio" if audio else "1920x1080", use_hls=True,
            remux_to_mp4=not audio, extension="m4a" if audio else extension, audio_only=audio,
            convert_video_to_m4a=audio and kwargs["video_fallback_for_audio"], expected_bytes=10,
        )

    monkeypatch.setattr(quick_downloads, "resolve_download_source", resolve_download_source)
    return probed


def test_best_video_plans_the_highest_rendition_into_the_quick_folder(quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker

    probed = _probe(monkeypatch)
    request = _request()
    folder = quick_folder(request.id)
    plan = prepare_quick_download_plan(request, folder, DownloadTracker())

    assert probed["url"] == "https://cdn.clips.example/abc.m3u8"
    assert probed["preferred_format"] == "format_4k" and probed["remux_video_to_mp4"] is True
    assert Path(plan.requested_destination) == folder / "Clip_ abc_.mp4"
    assert plan.download_mode == "temporary" and not plan.publication_requires_copy
    tags = dict(plan.metadata_tags)
    assert tags["title"] == "Clip: abc?" and tags["artist"] == "A Channel"
    [artwork] = plan.assets
    assert artwork.publish is False and plan.artwork_asset_id == "artwork"


def test_audio_is_taken_from_the_video_without_tags_when_asked(quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker

    probed = _probe(monkeypatch)
    request = _request(kind="audio", embed_metadata=False, embed_artwork=False)
    plan = prepare_quick_download_plan(request, quick_folder(request.id), DownloadTracker())

    assert probed["audio_only"] is True and probed["video_fallback_for_audio"] is True
    assert plan.source.convert_video_to_m4a and plan.requested_destination.endswith(".m4a")
    assert plan.metadata_tags == () and plan.assets == ()


def test_ytdlp_best_leaves_the_choice_to_ytdlp(quick_sources, temporary_root, monkeypatch):
    from backend.services import quick_downloads
    from downloader.lifecycle import DownloadTracker

    monkeypatch.setattr(quick_downloads, "resolve_download_source", lambda *_a, **_k: pytest.fail("not probed"))
    for container in ("mp4", "mkv"):
        request = _request("tube", container=container)
        plan = quick_downloads.prepare_quick_download_plan(request, quick_downloads.quick_folder(request.id), DownloadTracker())
        command = plan.source.ytdlp_command
        assert "-S" not in command and "-f" not in command
        assert command[:3] == ("yt-dlp", "--merge-output-format", container)
        assert plan.requested_destination.endswith(f".{container}")


@pytest.mark.parametrize(("choice", "options", "extension"), [
    ({"quality": 1080}, ("-S", "res:1080", "--merge-output-format", "mp4"), "mp4"),
    ({"quality": 720, "codec": "av1", "container": "mkv"}, ("-S", "res:720,vcodec:av1", "--merge-output-format", "mkv"), "mkv"),
    ({"codec": "h265"}, ("-S", "vcodec:h265", "--merge-output-format", "mp4"), "mp4"),
    ({"kind": "audio", "audio_format": "mp3", "audio_bitrate": 192},
     ("-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "192K"), "mp3"),
    ({"kind": "audio", "audio_format": "mp3"},
     ("-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "320K"), "mp3"),
])
def test_ytdlp_takes_the_chosen_quality_codec_and_audio_format(quick_sources, temporary_root, choice, options, extension):
    from backend.services import quick_downloads
    from downloader.lifecycle import DownloadTracker

    request = _request("tube", **choice)
    plan = quick_downloads.prepare_quick_download_plan(request, quick_downloads.quick_folder(request.id), DownloadTracker())
    assert plan.source.ytdlp_command[1:1 + len(options)] == options
    assert plan.requested_destination.endswith(f".{extension}")


def test_sources_without_format_choices_take_only_best_mp4_and_m4a(quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import QuickChoice, QuickDownloadRefused, prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker

    _probe(monkeypatch)
    assert QuickChoice().label == "Video · Best MP4"
    assert QuickChoice(quality=1080, container="mkv", codec="vp9").label == "Video · 1080p MKV · VP9"
    assert QuickChoice(kind="audio", audio_format="mp3").label == "Audio · MP3 320 kbps"
    with pytest.raises(ValueError):
        QuickChoice(quality=900)
    for choice in ({"quality": 1080}, {"container": "mkv"}, {"kind": "audio", "audio_format": "mp3"}):
        request = _request(**choice)
        with pytest.raises(QuickDownloadRefused, match="only as Best MP4 video or M4A audio"):
            prepare_quick_download_plan(request, quick_folder(request.id), DownloadTracker())


def test_the_option_list_has_each_quality_codec_and_size(quick_sources):
    from backend.services.quick_downloads import AudioOption, CodecOption, VideoOption, quick_options

    options = quick_options(quick_sources.tube, "https://tube.example/v/abc")
    assert options.format_choices and options.containers == ("mp4", "mkv")
    best, uhd, full_hd, low = options.videos
    # Best is what yt-dlp most likely takes: the highest, then the codec it prefers.
    assert best == VideoOption(None, 750, "av1", (
        CodecOption("h264", 360), CodecOption("vp9", 950), CodecOption("av1", 750),
    ))
    assert uhd == VideoOption(2160, 750, "av1", (CodecOption("vp9", 950), CodecOption("av1", 750)))
    # 1088p counts as 1080p, and a codec with no size has none.
    assert full_hd == VideoOption(1080, 360, "h264", (
        CodecOption("h264", 360), CodecOption("vp9", 250), CodecOption("av1", None),
    ))
    assert low == VideoOption(480, 70, "h264", (CodecOption("h264", 70),))
    assert options.audio == (
        AudioOption("m4a", size_bytes=50), AudioOption("mp3", 320, 4_000_000),
        AudioOption("mp3", 192, 2_400_000), AudioOption("mp3", 128, 1_600_000),
    )

    basic = quick_options(quick_sources.clips, "https://clips.example/v/abc")
    assert not basic.format_choices and basic.containers == ("mp4",)
    assert basic.videos == (VideoOption(None),) and basic.audio == (AudioOption("m4a"),)


def test_ytdlp_info_becomes_video_formats():
    from sources.ytdlp.source import video_formats

    formats = video_formats({"duration": 10, "formats": [
        {"format_id": "sb0", "format_note": "storyboard", "vcodec": "none", "acodec": "none"},
        {"vcodec": "avc1.640028", "acodec": "none", "width": 1920, "height": 1080, "filesize": 1000},
        {"vcodec": "vp09.00.40.08", "acodec": "none", "width": 1080, "height": 1920, "filesize_approx": 900},
        {"vcodec": "av01.0.08M.08", "acodec": "none", "width": 1280, "height": 720, "tbr": 800},
        {"vcodec": "hev1", "acodec": "none", "width": 3840, "height": 2160, "has_drm": True},
        {"vcodec": "none", "acodec": "mp4a.40.2", "filesize": 100},
        {"vcodec": "none", "acodec": "opus", "filesize": 120},
    ]})
    assert formats == VideoFormats(videos=(
        VideoFormat(1080, "h264", 1000), VideoFormat(1080, "vp9", 900), VideoFormat(720, "av1", 1_000_000),
    ), audio_size_bytes=120, duration=10.0)


def test_a_members_only_episode_asks_with_the_account(quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker

    _probe(monkeypatch)
    free = _request("wire", "free", LinkKind.EPISODE)
    prepare_quick_download_plan(free, quick_folder(free.id), DownloadTracker())
    assert quick_sources.wire.media_requests == [False]

    members = _request("wire", "members", LinkKind.EPISODE)
    prepare_quick_download_plan(members, quick_folder(members.id), DownloadTracker())
    assert quick_sources.wire.media_requests == [False, False, True]


def test_drm_at_download_time_is_refused(quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader import EncryptedMediaError
    from downloader.lifecycle import DownloadTracker

    _probe(monkeypatch)
    request = _request(slug="late-lock")
    with pytest.raises(EncryptedMediaError):
        prepare_quick_download_plan(request, quick_folder(request.id), DownloadTracker())


def test_a_full_temporary_folder_stops_the_download(quick_sources, temporary_root, monkeypatch):
    from config import get_settings
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker
    from downloader.storage.quick import InsufficientSpaceError

    _probe(monkeypatch)
    monkeypatch.setattr(get_settings().quick_download, "keep_free_gigabytes", 10 ** 9)
    request = _request()
    with pytest.raises(InsufficientSpaceError):
        prepare_quick_download_plan(request, quick_folder(request.id), DownloadTracker())


def test_the_worker_makes_a_ready_file_and_a_failure_leaves_nothing(quick_sources, temporary_root, monkeypatch):
    from downloader import coordinator
    from downloader.models import DownloadResult
    from downloader.storage.quick import list_quick_folders
    from task_manager.tasks.workers.quick_download import service

    _probe(monkeypatch)
    monkeypatch.setattr(service, "mark_quick_download_started", lambda: None)

    def transfer(_url, path, **_kwargs):
        Path(path).write_bytes(b"media")
        return DownloadResult(path, 5)

    monkeypatch.setattr(coordinator, "download_hls", transfer)
    monkeypatch.setattr(coordinator, "remux_to_mp4", lambda src, dst, **_k: Path(dst).write_bytes(Path(src).read_bytes()))
    monkeypatch.setattr(coordinator, "embed_media", lambda *_a, **_k: None)
    monkeypatch.setattr("downloader.sidecars.SidecarDownloads.get", lambda self, _id: None)
    request = _request(embed_artwork=False)

    result = service.run_quick_download(request.task_input())

    assert result.data["quick_download_id"] == request.id and result.data["size_bytes"] == 5
    [ready] = list_quick_folders(temporary_root)
    assert ready.id == request.id and ready.file.read_bytes() == b"media"
    assert ready.manifest.format == "Video · Best MP4"
    assert not any((temporary_root / ".vodloft-staging").iterdir())

    drm = _request(slug="late-lock")
    outcome = service.run_quick_download(drm.task_input())
    assert outcome.outcome == "failed" and "DRM" in outcome.summary
    assert [found.id for found in list_quick_folders(temporary_root)] == [request.id]


def test_sent_ranges_count_as_delivered_once_they_cover_the_file():
    from backend.services.quick_downloads import QuickDeliveries

    deliveries = QuickDeliveries()
    assert not deliveries.sent("a", 0, 100, 1000)
    assert not deliveries.sent("a", 0, 100, 1000)  # phones fetch the start twice
    assert not deliveries.sent("a", 500, 1000, 1000)
    assert deliveries.sent("a", 100, 500, 1000)
    assert not deliveries.sent("a", 0, 1000, 2000)  # forgotten after delivery


# --- Queue and API -----------------------------------------------------------


def _session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base
    from task_manager.scheduler.db import TaskDefinition

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    for key in ("download_episode", "download_movie", "quick_download"):
        session.add(TaskDefinition(key=key, title=key, description="", allowed_resource_types=[], default_max_retries=0))
    session.commit()
    return session, engine


def test_quick_downloads_take_free_slots_before_media_downloads(monkeypatch, quick_sources):
    from test_media_download_operations import _make_download

    from task_manager.scheduler.db import TaskRun
    from task_manager.scheduler.types import ResourceType, TaskStatus
    from task_manager.tasks import media_download_operations, quick_download_operations

    session, engine = _session()
    try:
        media = media_download_operations.create_media_download_operation(session, _make_download(session))
        quick = quick_download_operations.create_quick_download_operation(session, _request())
        session.commit()
        monkeypatch.setattr(media_download_operations, "get_settings", lambda: SimpleNamespace(
            download_settings=SimpleNamespace(max_concurrent_downloads=1),
        ))
        dispatched = []
        monkeypatch.setattr(quick_download_operations, "queue_task_after_commit", lambda _s, **kw: dispatched.append(kw))
        monkeypatch.setattr(media_download_operations, "_reserve_target_dispatch", lambda *_a: pytest.fail("no slot left"))

        assert media_download_operations.dispatch_queued_media_download_operations(session) == 1
        [run] = session.scalars(select(TaskRun)).all()
        assert run.resource_type == ResourceType.QUICK_DOWNLOAD and run.status == TaskStatus.SCHEDULED
        assert dispatched[0]["operation_ids"] == (quick.id,)
        assert dispatched[0]["request"]["id"] == quick.context["quick_download_id"]
        # The reserved quick download now holds the only slot.
        assert media_download_operations.remaining_media_download_budget(session) == 0
        assert media.status == "QUEUED"
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api(quick_sources, temporary_root, task_database, monkeypatch):
    from backend.api.endpoints.quick_downloads import router as router_module
    from backend.api.endpoints.sources import service as sources_service
    from task_manager.scheduler.db import TaskDefinition
    from task_manager.tasks import quick_download_operations

    from backend.db.models import QuickDownloadHistory
    from config import get_settings

    session = task_database()
    QuickDownloadHistory.__table__.create(bind=session.get_bind())
    session.add(TaskDefinition(key="quick_download", title="Quick download", description="", allowed_resource_types=[]))
    session.commit()
    monkeypatch.setattr(get_settings().quick_download, "keep_history", True)

    @contextmanager
    def db_session():
        yield session

    monkeypatch.setattr(router_module, "db_session", db_session)
    monkeypatch.setattr(sources_service, "preferred_sources", lambda _s: {})
    monkeypatch.setattr(quick_download_operations, "queue_task_after_commit", lambda *_a, **_k: None)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api")
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, session=session)
    session.close()


def test_starting_a_quick_download_queues_one_operation(api):
    response = api.client.post("/api/quick-downloads", json={"url": "https://clips.example/v/abc", "choice": {"kind": "audio"}})
    assert response.status_code == 202, response.text
    body = response.json()

    listed = api.client.get("/api/quick-downloads").json()
    [active] = listed["active"]
    assert active["id"] == body["operationId"] and active["kind"] == "quick.download"
    assert active["context"]["quick_download_id"] == body["quickDownloadId"]
    assert active["context"]["choice"] == "Audio · M4A"
    assert listed["ready"] == []


@pytest.mark.parametrize(("url", "message"), [
    ("https://clips.example/v/locked-1", "DRM"),
    ("https://clips.example/channel-1", "not a whole show"),
])
def test_links_that_cannot_be_quick_downloaded_are_refused(api, url, message):
    response = api.client.post("/api/quick-downloads", json={"url": url})
    assert response.status_code == 422 and message in response.json()["detail"]


def test_options_list_formats_or_say_why_not(api):
    response = api.client.post("/api/quick-downloads/options", json={"url": "https://tube.example/v/abc"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["link"]["preview"]["title"] == "Clip: abc?" and body["refused"] is None
    assert body["formatChoices"] is True and body["containers"] == ["mp4", "mkv"]
    assert [video["quality"] for video in body["videos"]] == [None, 2160, 1080, 480]
    assert body["videos"][2]["codecs"][0] == {"codec": "h264", "sizeBytes": 360}
    assert body["audio"][1] == {"audioFormat": "mp3", "bitrate": 320, "sizeBytes": 4_000_000}

    basic = api.client.post("/api/quick-downloads/options", json={"url": "https://clips.example/v/abc"}).json()
    assert basic["formatChoices"] is False and [video["quality"] for video in basic["videos"]] == [None]

    locked = api.client.post("/api/quick-downloads/options", json={"url": "https://clips.example/v/locked-1"}).json()
    assert "DRM" in locked["refused"] and locked["videos"] == []


def test_choices_a_source_does_not_offer_are_refused(api):
    response = api.client.post("/api/quick-downloads", json={
        "url": "https://clips.example/v/abc", "choice": {"quality": 1080},
    })
    assert response.status_code == 422 and "only as Best MP4" in response.json()["detail"]
    response = api.client.post("/api/quick-downloads", json={
        "url": "https://tube.example/v/abc", "choice": {"quality": 900},
    })
    assert response.status_code == 422
    response = api.client.post("/api/quick-downloads", json={
        "url": "https://tube.example/v/abc", "choice": {"kind": "audio", "audioFormat": "mp3", "audioBitrate": 192},
    })
    assert response.status_code == 202, response.text
    [active] = api.client.get("/api/quick-downloads").json()["active"]
    assert active["context"]["choice"] == "Audio · MP3 192 kbps"


def _ready_file(temporary_root: Path, content: bytes = b"0123456789", quick_id: str | None = None) -> str:
    from datetime import datetime, timedelta, timezone

    from downloader.storage.quick import QuickManifest, new_quick_download_id, reserve_quick_folder, write_manifest

    quick_id = quick_id or new_quick_download_id()
    folder = reserve_quick_folder(temporary_root, quick_id)
    (folder / "Clip é.mp4").write_bytes(content)
    now = datetime.now(timezone.utc)
    write_manifest(folder, QuickManifest(
        id=quick_id, title="Clip é", file_name="Clip é.mp4", size_bytes=len(content), format="Video · Best MP4",
        created_at=now, expires_at=now + timedelta(hours=24), details={"source_key": "clips", "source_name": "Clips"},
    ))
    return quick_id


def test_a_ready_file_downloads_in_ranges_and_is_deleted_after_the_grace_period(api, temporary_root, monkeypatch):
    from config import get_settings
    from downloader.storage.quick import open_quick_folder

    quick_id = _ready_file(temporary_root)
    [ready] = api.client.get("/api/quick-downloads").json()["ready"]
    assert ready["id"] == quick_id and ready["sourceName"] == "Clips" and ready["state"] == "ready"

    head = api.client.head(f"/api/quick-downloads/{quick_id}/file")
    assert head.headers["content-length"] == "10"
    assert "filename*=UTF-8''Clip%20%C3%A9.mp4" in head.headers["content-disposition"]
    assert head.headers["x-accel-buffering"] == "no"

    first = api.client.get(f"/api/quick-downloads/{quick_id}/file", headers={"Range": "bytes=0-3"})
    assert first.status_code == 206 and first.content == b"0123"
    assert first.headers["content-range"] == "bytes 0-3/10"
    assert open_quick_folder(temporary_root, quick_id).manifest.state == "ready"
    from task_manager.scheduler.operations import list_operations
    assert not list_operations(kind="quick.delivered")

    rest = api.client.get(f"/api/quick-downloads/{quick_id}/file", headers={"Range": "bytes=4-"})
    assert rest.content == b"456789"
    manifest = open_quick_folder(temporary_root, quick_id).manifest
    assert manifest.state == "delivered"
    # The frontend puller hears of it as a finished operation and refreshes the lists.
    [delivered] = list_operations(kind="quick.delivered", relevant=True)
    assert delivered.status == "SUCCEEDED" and delivered.source == "SYSTEM"
    assert delivered.context["quick_download_id"] == quick_id
    assert (manifest.expires_at - manifest.delivered_at).total_seconds() == 600

    assert api.client.get(f"/api/quick-downloads/{quick_id}/file", headers={"Range": "bytes=20-"}).status_code == 416

    monkeypatch.setattr(get_settings().quick_download, "keep_downloaded_minutes", 0)
    other = _ready_file(temporary_root)
    assert api.client.get(f"/api/quick-downloads/{other}/file").content == b"0123456789"
    assert open_quick_folder(temporary_root, other) is None
    assert api.client.get(f"/api/quick-downloads/{other}/file").status_code == 404


def test_discarding_a_ready_file_deletes_it(api, temporary_root):
    from downloader.storage.quick import open_quick_folder

    quick_id = _ready_file(temporary_root)
    assert api.client.delete(f"/api/quick-downloads/{quick_id}").status_code == 204
    assert open_quick_folder(temporary_root, quick_id) is None
    assert api.client.delete(f"/api/quick-downloads/{quick_id}").status_code == 404


def _rules(monkeypatch, **values):
    from config import get_settings

    for key, value in values.items():
        monkeypatch.setattr(get_settings().quick_download, key, value)


def _start(api, url, **choice):
    return api.client.post("/api/quick-downloads", json={"url": url, "choice": choice})


def test_rules_refuse_what_settings_do_not_allow(api, monkeypatch):
    tube = "https://tube.example/v/abc"
    _rules(monkeypatch, max_quality="1080p", allow_mkv=False, allow_mp3=False)
    assert "above the 1080p limit" in _start(api, tube, quality=2160).json()["detail"]
    assert "MKV is not allowed" in _start(api, tube, container="mkv").json()["detail"]
    assert "MP3 is not allowed" in _start(api, tube, kind="audio", audioFormat="mp3").json()["detail"]
    assert _start(api, tube, quality=1080).status_code == 202

    _rules(monkeypatch, max_quality="best", allow_mkv=True, allow_mp3=True, fixed_codec="av1")
    # 480p is only offered in H.264, so a fixed AV1 cannot be met.
    assert "not offered in AV1" in _start(api, tube, quality=480).json()["detail"]
    assert _start(api, tube, quality=1080).status_code == 202

    _rules(monkeypatch, fixed_codec="auto", max_file_gigabytes=300 / 1024 ** 3)
    assert "more than the" in _start(api, tube, quality=1080).json()["detail"]
    assert _start(api, tube, quality=480).status_code == 202

    _rules(monkeypatch, max_file_gigabytes=0, max_duration_minutes=1)
    assert "longer than the 1 minutes" in _start(api, tube).json()["detail"]

    _rules(monkeypatch, max_duration_minutes=0, allowed_sources="clips, wire")
    assert "from Tube is turned off" in _start(api, tube).json()["detail"]
    assert _start(api, "https://clips.example/v/abc").status_code == 202


def test_locked_defaults_and_a_quality_limit_shape_the_download(api, quick_sources, temporary_root, monkeypatch):
    from backend.services.quick_downloads import prepare_quick_download_plan, quick_folder
    from downloader.lifecycle import DownloadTracker

    _rules(monkeypatch, lock_to_defaults=True, default_kind="audio", default_audio_format="mp3", default_mp3_bitrate=128)
    assert _start(api, "https://tube.example/v/abc", quality=2160).status_code == 202
    [operation] = api.client.get("/api/quick-downloads").json()["active"]
    assert operation["context"]["choice"] == "Audio · MP3 128 kbps"

    _rules(monkeypatch, lock_to_defaults=False, max_quality="720p", fixed_codec="h264", max_file_gigabytes=1)
    request = _request("tube", codec="h264")
    plan = prepare_quick_download_plan(request, quick_folder(request.id), DownloadTracker())
    command = plan.source.ytdlp_command
    # Best is held to the limit, and the codec is the only one taken.
    assert command[command.index("-S") + 1] == "res:720,vcodec:h264"
    assert command[command.index("-f") + 1] == "bv*[vcodec~='^(avc|h264)']+ba/b[vcodec~='^(avc|h264)']"
    assert command[command.index("--max-filesize") + 1] == str(1024 ** 3)


def test_the_history_follows_each_quick_download_to_its_end(api, temporary_root, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.services import quick_download_history as history
    from backend.services.quick_downloads import sweep_quick_downloads
    from task_manager.scheduler.operation_control import cancel_operation

    monkeypatch.setattr("backend.services.quick_download_history.get_session", lambda: api.session)
    monkeypatch.setattr(api.session, "close", lambda: None)

    downloaded = _start(api, "https://clips.example/v/abc").json()
    expired = _start(api, "https://clips.example/v/def", kind="audio").json()
    canceled = _start(api, "https://clips.example/v/ghi").json()
    assert _start(api, "https://clips.example/v/locked-1").status_code == 422
    rows = {row["quickDownloadId"]: row for row in api.client.get("/api/quick-downloads/history").json()}
    assert rows[downloaded["quickDownloadId"]]["outcome"] == "working"
    [refused] = [row for row in rows.values() if row["outcome"] == "refused"]
    assert refused["message"] == "Protected by DRM" and refused["title"] == "Clip: locked-1?"

    # The worker makes two files ready; the third is canceled before it starts.
    for done in (downloaded, expired):
        history.record_outcome(done["quickDownloadId"], history.READY, size_bytes=10)
        _ready_file(temporary_root, quick_id=done["quickDownloadId"])
    cancel_operation(canceled["operationId"], reason="Canceled by user")
    api.client.get(f"/api/quick-downloads/{downloaded['quickDownloadId']}/file")
    sweep_quick_downloads(now=datetime.now(timezone.utc) + timedelta(days=2))

    rows = {row["quickDownloadId"]: row for row in api.client.get("/api/quick-downloads/history").json()}
    assert rows[downloaded["quickDownloadId"]]["outcome"] == "downloaded"
    assert rows[expired["quickDownloadId"]]["outcome"] == "expired"
    assert rows[expired["quickDownloadId"]]["format"] == "Audio · M4A"
    assert rows[expired["quickDownloadId"]]["choice"]["kind"] == "audio"
    assert rows[canceled["quickDownloadId"]]["outcome"] == "canceled"

    # Clearing keeps what is still going on; old entries are forgotten after the retention period.
    working = _start(api, "https://clips.example/v/jkl").json()
    assert api.client.delete("/api/quick-downloads/history").status_code == 204
    [left] = api.client.get("/api/quick-downloads/history").json()
    assert left["quickDownloadId"] == working["quickDownloadId"]
    assert history.forget_old_history(now=datetime.now(timezone.utc) + timedelta(days=91)) == 1

    _rules(monkeypatch, keep_history=False)
    _start(api, "https://clips.example/v/mno")
    assert api.client.get("/api/quick-downloads/history").json() == []


def test_every_quick_download_setting_is_sent_under_its_editable_path():
    from backend.api.models.settings import SettingsValues, UI_SETTING_PATHS
    from config.settings.settings import AppSettings

    sent = SettingsValues.from_app_settings(AppSettings()).model_dump(mode="json", by_alias=True)["quickDownload"]

    assert {f"quickDownload.{key}" for key in sent} <= set(UI_SETTING_PATHS)
    assert sent["allowM4a"] is True
