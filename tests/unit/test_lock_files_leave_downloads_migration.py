"""The background migration that removes the old lock folders from the download root."""
from __future__ import annotations

import importlib

migration = importlib.import_module(
    "backend.db.background_migrations.versions.a3d91f5c07e2_lock_files_leave_downloads"
)


def test_old_lock_folders_are_removed(tmp_path):
    root = tmp_path / "downloads"
    (root / ".vodloft-assets-locks").mkdir(parents=True)
    (root / ".vodloft-assets-locks" / "abc.lock").touch()
    (root / ".vodloft-index-locks").mkdir()
    (root / ".vodloft-index-locks" / "1-2.lock").touch()
    (root / "Show").mkdir()
    (root / "Show" / "Episode.mp4").write_bytes(b"media")

    assert migration._remove_old_lock_folders(root) == 2
    assert sorted(path.name for path in root.iterdir()) == ["Show"]
    assert (root / "Show" / "Episode.mp4").read_bytes() == b"media"
    # Running it again finds nothing left to remove.
    assert migration._remove_old_lock_folders(root) == 0


def test_a_lock_folder_holding_other_files_stays(tmp_path):
    root = tmp_path / "downloads"
    (root / ".vodloft-index-locks").mkdir(parents=True)
    (root / ".vodloft-index-locks" / "1-2.lock").touch()
    (root / ".vodloft-index-locks" / "notes.txt").write_text("mine")

    assert migration._remove_old_lock_folders(root) == 0
    assert sorted(path.name for path in (root / ".vodloft-index-locks").iterdir()) == ["notes.txt"]
