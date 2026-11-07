"""Thumbnails VODLoft makes from the first frame of a video that has no picture."""
from __future__ import annotations

import subprocess

import pytest

from sources import registry
from sources.ytdlp import thumbnails

from test_ytdlp_collections import ListedSource, _collection, _video, session  # noqa: F401


class _Head:
    def __init__(self, status: int):
        self.status = status
        self.urls: list[str] = []

    def __call__(self, url, **_kwargs):
        self.urls.append(url)
        return type("Response", (), {"status_code": self.status})()


class FramingSource(ListedSource):
    """Takes a frame of every video whose picture is missing, and records what it was asked."""

    def __init__(self):
        super().__init__()
        self.asked: list[tuple[str, str | None]] = []

    def first_frame(self, url, image_url):
        self.asked.append((url, image_url))
        return b"jpeg" if image_url is None or "placeholder" in image_url else None


@pytest.fixture
def framing(monkeypatch):
    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    return registry.register(FramingSource())


@pytest.fixture
def thumbnail_root(monkeypatch, tmp_path):
    from config import get_settings

    monkeypatch.setattr(get_settings().download_settings, "thumbnail_root", tmp_path / ".vodloft-thumbnails")
    return tmp_path / ".vodloft-thumbnails"


def test_the_thumbnail_folder_is_next_to_the_config_file(tmp_path, monkeypatch):
    from config.settings.submodels import DownloadSettings

    monkeypatch.setenv("VL_CONFIG_FILE", str(tmp_path / "config" / "config.yml"))
    settings = DownloadSettings(download_root=tmp_path / "downloads")
    assert settings.thumbnail_root == tmp_path / "config" / "thumbnails"


@pytest.mark.parametrize("status, missing", [(404, True), (200, False)])
def test_a_youtube_still_is_missing_when_youtube_answers_404(monkeypatch, status, missing):
    head = _Head(status)
    monkeypatch.setattr(thumbnails.requests, "head", head)
    assert thumbnails.still_missing("https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg") is missing
    assert head.urls == ["https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"]


def test_no_picture_is_missing_and_other_pictures_are_taken_as_they_are(monkeypatch):
    head = _Head(404)
    monkeypatch.setattr(thumbnails.requests, "head", head)
    assert thumbnails.still_missing(None) is True
    assert thumbnails.still_missing("https://example.com/picture.jpg") is False
    assert thumbnails.still_missing("thumbnails/abc.jpg") is False
    assert head.urls == []


def test_first_frame_downloads_the_first_seconds_and_keeps_a_frame(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(thumbnails.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            Path(command[command.index("-o") + 1]).write_bytes(b"clip")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        assert Path(command[command.index("-i") + 1]).read_bytes() == b"clip"
        return subprocess.CompletedProcess(command, 0, stdout=b"jpeg", stderr=b"")

    monkeypatch.setattr(thumbnails.subprocess, "run", run)
    assert thumbnails.first_frame("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == b"jpeg"
    download, frame = calls
    assert download[download.index("--download-sections") + 1] == "*0-4"
    assert download[-1] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert frame[0] == "/usr/bin/ffmpeg" and frame[-1] == "pipe:1"


def test_first_frame_gives_up_when_the_download_fails(monkeypatch):
    monkeypatch.setattr(thumbnails.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        thumbnails.subprocess, "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="ERROR: HTTP Error 403: Forbidden"),
    )
    assert thumbnails.first_frame("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is None


def test_the_ytdlp_source_takes_no_frame_when_the_still_is_there(monkeypatch):
    from sources.ytdlp import YtDlpSource

    monkeypatch.setattr(thumbnails, "still_missing", lambda url: False)
    monkeypatch.setattr(thumbnails, "first_frame", lambda url: pytest.fail("no frame should be taken"))
    assert YtDlpSource().first_frame("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg") is None


def test_new_episodes_without_a_picture_get_their_first_frame(framing, session, thumbnail_root):  # noqa: F811
    from backend.db.models import Episode
    from backend.services.thumbnails import newest_media_item_id, take_first_frames
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _collection(session, source_key="listed")
    missing = _video("a", 2023)
    missing = type(missing)(**{**missing.__dict__, "image_url": "https://i.ytimg.com/vi/a/placeholder.jpg"})
    framing.videos = [missing, _video("b", 2023, 2)]
    newest = newest_media_item_id(session)
    index_listed_collection(session, collection_id=collection.id, source=framing)
    session.commit()

    ids = [episode.id for episode in session.query(Episode).filter(Episode.id > newest)]
    assert take_first_frames(ids) == 1

    a, b = session.query(Episode).order_by(Episode.index).all()
    assert a.thumbnail_landscape_path == a.background_image_path == f"thumbnails/{a.uuid}.jpg"
    assert (thumbnail_root / f"{a.uuid}.jpg").read_bytes() == b"jpeg"
    assert b.thumbnail_landscape_path == "https://i.ytimg.com/vi/b/hq.jpg"

    # A frame VODLoft made is not looked at again.
    framing.asked.clear()
    assert take_first_frames(ids) == 0
    assert [url for url, _ in framing.asked] == ["https://www.youtube.com/watch?v=b"]


def test_a_refresh_keeps_a_frame_vodloft_made(framing, session, thumbnail_root):  # noqa: F811
    from backend.db.models import Episode
    from sources import ItemRefresh
    from task_manager.tasks.helpers.listed_collections import index_listed_collection, refresh_listed_collection

    collection = _collection(session, source_key="listed")
    framing.videos = [_video("a", 2023)]
    index_listed_collection(session, collection_id=collection.id, source=framing)
    episode = session.query(Episode).one()
    episode.thumbnail_landscape_path = episode.background_image_path = "thumbnails/a.jpg"
    session.commit()

    framing.refresh_items = lambda url, items: ItemRefresh(
        details={"a": type(framing.videos[0])(**{**framing.videos[0].__dict__, "title": "Renamed"})}, removed=frozenset(),
    )
    refresh_listed_collection(session, collection_id=collection.id, source=framing)
    episode = session.query(Episode).one()
    assert episode.title == "Renamed"
    assert episode.thumbnail_landscape_path == "thumbnails/a.jpg"


@pytest.mark.parametrize("name", ["../secret.jpg", "a.png", "a/b.jpg", ".jpg"])
def test_only_thumbnail_names_are_served(thumbnail_root, name):
    from backend.services.thumbnails import thumbnail_file

    thumbnail_root.mkdir()
    (thumbnail_root / "a.png").write_bytes(b"x")
    assert thumbnail_file(name) is None


def test_a_saved_thumbnail_is_served(thumbnail_root):
    from backend.services.thumbnails import thumbnail_file

    thumbnail_root.mkdir()
    (thumbnail_root / "abc-123.jpg").write_bytes(b"jpeg")
    assert thumbnail_file("abc-123.jpg") == thumbnail_root / "abc-123.jpg"


def test_a_frame_vodloft_made_is_the_thumbnail_a_download_takes(thumbnail_root):
    from types import SimpleNamespace

    from backend.services.download_metadata import select_thumbnail

    thumbnail_root.mkdir()
    (thumbnail_root / "abc-123.jpg").write_bytes(b"jpeg")
    made = SimpleNamespace(
        thumbnail_square_path=None, thumbnail_portrait_path=None,
        thumbnail_landscape_path="thumbnails/abc-123.jpg", background_image_path="thumbnails/abc-123.jpg",
    )
    assert select_thumbnail(made) == thumbnail_root / "abc-123.jpg"
    # A frame that is gone is no thumbnail.
    gone = SimpleNamespace(**{**made.__dict__, "thumbnail_landscape_path": "thumbnails/gone.jpg", "background_image_path": None})
    assert select_thumbnail(gone) is None
