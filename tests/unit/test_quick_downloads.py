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

from sources import EpisodeMedia, Feature, LinkKind, Playback, PlaybackKind, ResolvedLink, Source, VideoDetails, registry


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

    session = task_database()
    session.add(TaskDefinition(key="quick_download", title="Quick download", description="", allowed_resource_types=[]))
    session.commit()

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


def _ready_file(temporary_root: Path, content: bytes = b"0123456789") -> str:
    from datetime import datetime, timedelta, timezone

    from downloader.storage.quick import QuickManifest, new_quick_download_id, reserve_quick_folder, write_manifest

    quick_id = new_quick_download_id()
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

    rest = api.client.get(f"/api/quick-downloads/{quick_id}/file", headers={"Range": "bytes=4-"})
    assert rest.content == b"456789"
    manifest = open_quick_folder(temporary_root, quick_id).manifest
    assert manifest.state == "delivered"
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
