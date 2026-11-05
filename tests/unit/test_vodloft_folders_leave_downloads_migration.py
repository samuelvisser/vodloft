"""The background migration that moves lock files and thumbnails out of the download root."""
from __future__ import annotations

import importlib

migration = importlib.import_module(
    "backend.db.background_migrations.versions.a3d91f5c07e2_vodloft_folders_leave_downloads"
)


def test_old_lock_folders_are_removed_and_thumbnails_move(tmp_path):
    root = tmp_path / "downloads"
    thumbnails = tmp_path / "config" / "thumbnails"
    (root / ".vodloft-assets-locks").mkdir(parents=True)
    (root / ".vodloft-assets-locks" / "abc.lock").touch()
    (root / ".vodloft-index-locks").mkdir()
    (root / ".vodloft-index-locks" / "1-2.lock").touch()
    (root / ".vodloft-thumbnails").mkdir()
    (root / ".vodloft-thumbnails" / "abc.jpg").write_bytes(b"jpeg")
    (root / "Show").mkdir()
    (root / "Show" / "Episode.mp4").write_bytes(b"media")

    assert migration._move_out_of_download_root(root, thumbnails) == 3
    assert sorted(path.name for path in root.iterdir()) == ["Show"]
    assert (root / "Show" / "Episode.mp4").read_bytes() == b"media"
    assert (thumbnails / "abc.jpg").read_bytes() == b"jpeg"
    # Running it again finds nothing left to move.
    assert migration._move_out_of_download_root(root, thumbnails) == 0


def test_a_lock_folder_holding_other_files_stays(tmp_path):
    root = tmp_path / "downloads"
    (root / ".vodloft-index-locks").mkdir(parents=True)
    (root / ".vodloft-index-locks" / "1-2.lock").touch()
    (root / ".vodloft-index-locks" / "notes.txt").write_text("mine")

    assert migration._move_out_of_download_root(root, tmp_path / "thumbnails") == 0
    assert sorted(path.name for path in (root / ".vodloft-index-locks").iterdir()) == ["notes.txt"]


def test_thumbnails_stay_when_the_thumbnail_folder_is_still_the_old_one(tmp_path):
    root = tmp_path / "downloads"
    (root / ".vodloft-thumbnails").mkdir(parents=True)
    (root / ".vodloft-thumbnails" / "abc.jpg").write_bytes(b"jpeg")

    assert migration._move_out_of_download_root(root, root / ".vodloft-thumbnails") == 0
    assert (root / ".vodloft-thumbnails" / "abc.jpg").read_bytes() == b"jpeg"
