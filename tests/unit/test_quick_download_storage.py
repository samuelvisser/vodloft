from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from downloader.storage.quick import (
    InsufficientSpaceError,
    QuickManifest,
    ensure_free_space,
    list_quick_folders,
    new_quick_download_id,
    open_quick_folder,
    quick_root,
    read_manifest,
    reserve_quick_folder,
    sweep_quick_folders,
    write_manifest,
)


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _manifest(quick_id: str, file_name: str = "Big Buck Bunny.mp4", **changes) -> QuickManifest:
    values = dict(
        id=quick_id, title="Big Buck Bunny", file_name=file_name, size_bytes=14,
        format="Video · 1080p MP4", created_at=NOW, expires_at=NOW + timedelta(hours=24),
    )
    values.update(changes)
    return QuickManifest(**values)


def _files_under(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if path.is_file()}


def _download_into_ready_folder(tmp_path: Path, monkeypatch) -> tuple[Path, str, Path]:
    from downloader import coordinator
    from downloader.lifecycle import DownloadTracker
    from downloader.models import DownloadResult
    from downloader.plan import ResolvedDownloadSource, build_download_plan

    temporary_root = tmp_path / "temporary"
    quick_id = new_quick_download_id()
    folder = reserve_quick_folder(temporary_root, quick_id)
    source = ResolvedDownloadSource("https://example.test/video.mp4", "1080p", False, False, "mp4", False)

    def transfer(_url, path, **_kwargs):
        Path(path).write_bytes(b"complete media")
        return DownloadResult(path, 14)

    monkeypatch.setattr(coordinator, "download_file", transfer)
    with DownloadTracker() as tracker:
        plan = build_download_plan(
            source=source, requested_destination=folder / "Big Buck Bunny.mp4",
            temporary_root=temporary_root, download_mode="temporary", attempt_id=tracker.attempt_id,
        )
        assert not plan.publication_requires_copy
        execution = coordinator.execute_download_plan(plan, tracker=tracker)
        write_manifest(folder, _manifest(quick_id))
        execution.cleanup_workspace()
    return temporary_root, quick_id, Path(execution.result.path)


def test_a_quick_download_is_published_into_its_ready_folder_and_nowhere_else(tmp_path, monkeypatch):
    temporary_root, quick_id, published = _download_into_ready_folder(tmp_path, monkeypatch)

    assert published == quick_root(temporary_root) / quick_id / "Big Buck Bunny.mp4"
    assert published.read_bytes() == b"complete media"
    # Every byte stayed inside the temporary root, and the staging workspace is gone.
    assert {path.relative_to(tmp_path) for path in _files_under(tmp_path)} == {
        Path("temporary/.vodloft-quick") / quick_id / "Big Buck Bunny.mp4",
        Path("temporary/.vodloft-quick") / quick_id / "manifest.json",
    }
    [folder] = list_quick_folders(temporary_root)
    assert folder.id == quick_id and folder.file == published
    assert folder.manifest == _manifest(quick_id)


def test_a_ready_file_survives_a_restart_and_is_deleted_at_expiry(tmp_path, monkeypatch):
    from downloader.storage.temporary import cleanup_abandoned_temporary_downloads

    temporary_root, quick_id, published = _download_into_ready_folder(tmp_path, monkeypatch)

    # Startup recovery: the library's staging cleanup and the quick download sweep.
    cleanup_abandoned_temporary_downloads(temporary_root, tmp_path / "library", is_committed=lambda *_: False)
    assert sweep_quick_folders(temporary_root, now=NOW, remove_unfinished=True).expired == ()
    assert published.is_file()

    sweep = sweep_quick_folders(temporary_root, now=NOW + timedelta(hours=24))
    assert [manifest.id for manifest in sweep.expired] == [quick_id]
    assert not (quick_root(temporary_root) / quick_id).exists()


def test_unfinished_folders_are_removed_only_by_startup_recovery(tmp_path):
    temporary_root = tmp_path / "temporary"
    quick_id = new_quick_download_id()
    folder = reserve_quick_folder(temporary_root, quick_id)
    (folder / "Half a file.mp4").write_bytes(b"half")
    unrelated = quick_root(temporary_root) / "not-a-quick-download"
    unrelated.mkdir()

    assert sweep_quick_folders(temporary_root, now=NOW).unfinished == ()
    assert folder.is_dir()

    assert sweep_quick_folders(temporary_root, now=NOW, remove_unfinished=True).unfinished == (quick_id,)
    assert not folder.exists()
    assert unrelated.is_dir()


def test_staging_recovery_drops_a_quick_workspace_without_touching_quick_folders(tmp_path):
    from downloader.storage.temporary import (
        cleanup_abandoned_temporary_downloads,
        create_temporary_download_workspace,
    )

    temporary_root = tmp_path / "temporary"
    quick_id = new_quick_download_id()
    folder = reserve_quick_folder(temporary_root, quick_id)
    workspace = create_temporary_download_workspace(temporary_root, folder / "Video.mp4")
    workspace.path.write_bytes(b"partial")
    (workspace.workspace / ".vodloft-publication").write_bytes(b"\0unreadable")
    assert workspace.workspace.name.startswith("quick-")
    library = create_temporary_download_workspace(temporary_root, tmp_path / "library" / "Episode.mp4")
    assert library.workspace.name.startswith("attempt-")

    removed = cleanup_abandoned_temporary_downloads(temporary_root, tmp_path / "library", is_committed=lambda *_: False)

    assert removed == 2
    assert not workspace.workspace.exists()
    assert folder.is_dir()


def test_manifest_round_trip_and_rejection(tmp_path):
    quick_id = new_quick_download_id()
    folder = reserve_quick_folder(tmp_path, quick_id)
    manifest = _manifest(quick_id, details={"source_key": "ytdlp"})
    write_manifest(folder, manifest)
    assert read_manifest(folder) == manifest
    assert [name for name in os.listdir(folder)] == ["manifest.json"]

    # No file next to it yet: not a ready download.
    assert open_quick_folder(tmp_path, quick_id).manifest is None
    (folder / manifest.file_name).write_bytes(b"x")
    assert open_quick_folder(tmp_path, quick_id).manifest == manifest

    (folder / "manifest.json").write_text('{"version": 1, "id": "x"}')
    assert read_manifest(folder) is None
    with pytest.raises(ValueError):
        write_manifest(folder, _manifest(new_quick_download_id()))
    with pytest.raises(ValueError):
        reserve_quick_folder(tmp_path, "../escape")
    assert open_quick_folder(tmp_path, "../escape") is None
    assert QuickManifest.from_json(_manifest(quick_id, file_name="../x.mp4").to_json()) is None


def test_delivery_keeps_the_file_for_the_grace_period_only():
    manifest = _manifest(new_quick_download_id())
    delivered = manifest.delivered(NOW + timedelta(hours=1), keep_for=timedelta(minutes=10))
    assert delivered.state == "delivered"
    assert delivered.expires_at == NOW + timedelta(hours=1, minutes=10)
    # A second full download does not move the deadline.
    assert delivered.delivered(NOW + timedelta(hours=2), keep_for=timedelta(minutes=10)) == delivered
    # Never later than the original expiry.
    late = manifest.delivered(NOW + timedelta(hours=23, minutes=55), keep_for=timedelta(minutes=10))
    assert late.expires_at == manifest.expires_at


def test_free_space_check(tmp_path, monkeypatch):
    import shutil
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: usage(100 * 2**30, 90 * 2**30, 10 * 2**30))

    ensure_free_space(tmp_path / "missing", expected_bytes=4 * 2**30, keep_free_bytes=5 * 2**30)
    ensure_free_space(tmp_path, expected_bytes=None, keep_free_bytes=5 * 2**30)
    with pytest.raises(InsufficientSpaceError, match="10.0 GB free"):
        ensure_free_space(tmp_path, expected_bytes=6 * 2**30, keep_free_bytes=5 * 2**30)


def test_startup_recovery_and_the_scheduled_sweep_use_the_quick_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import backend.api.endpoints.feeds.cached_video as cached_video
    import backend.services.download_recovery as download_recovery
    from backend.services.quick_downloads import sweep_quick_downloads
    from config import get_settings

    temporary_root = tmp_path / "temporary"
    ready, unfinished = new_quick_download_id(), new_quick_download_id()
    folder = reserve_quick_folder(temporary_root, ready)
    (folder / "Video.mp4").write_bytes(b"x")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    write_manifest(folder, _manifest(ready, file_name="Video.mp4", expires_at=expires_at))
    reserve_quick_folder(temporary_root, unfinished)
    monkeypatch.setattr(cached_video, "cleanup_expired_rss_cache", lambda: 0)
    monkeypatch.setattr(get_settings().quick_download, "keep_history", False)

    recovery = download_recovery.recover_download_filesystem(SimpleNamespace(
        download_root=tmp_path / "downloads", temporary_download_root=temporary_root,
    ))
    assert recovery.quick_downloads == 1
    assert [found.id for found in list_quick_folders(temporary_root)] == [ready]

    monkeypatch.setattr(get_settings().download_settings, "temporary_download_root", temporary_root)
    assert sweep_quick_downloads().expired == ()
    assert [m.id for m in sweep_quick_downloads(now=expires_at).expired] == [ready]
