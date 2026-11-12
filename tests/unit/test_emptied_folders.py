"""Folders that renamed files left empty are removed, and nothing that holds a file ever is."""
from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from downloader.storage import empty_folders
from downloader.storage.empty_folders import remove_emptied_folders

from test_profile_moves import library  # noqa: F401  (fixture)
from test_collection_asset_reconciliation import _active, _target, writer  # noqa: F401  (fixture)


@pytest.fixture
def root(tmp_path):
    root = (tmp_path / "downloads").resolve()
    root.mkdir()
    return root


def _folder(root: Path, *parts: str) -> Path:
    folder = root.joinpath(*parts)
    folder.mkdir(parents=True)
    return folder


def test_an_empty_folder_and_its_empty_parents_are_removed_up_to_the_root(root):
    episode = _folder(root, "Video", "show-slug", "2015-12-23 - ep-46")

    removed = remove_emptied_folders([episode], root=root)

    assert removed == [episode, episode.parent, episode.parent.parent]
    assert root.is_dir() and list(root.iterdir()) == []


@pytest.mark.parametrize("leftover", ["notes.txt", ".hidden", ".DS_Store", "Thumbs.db"])
def test_a_folder_with_any_file_left_stays_with_its_parents(root, leftover):
    episode = _folder(root, "show-slug", "episode")
    (episode / leftover).write_text("the user's own")

    assert remove_emptied_folders([episode], root=root) == []
    assert (episode / leftover).read_text() == "the user's own"


def test_a_leftover_higher_up_stops_the_walk_there(root):
    episode = _folder(root, "show-slug", "episode")
    (root / "show-slug" / "poster.jpg").write_bytes(b"custom")

    assert remove_emptied_folders([episode], root=root) == [episode]
    assert (root / "show-slug" / "poster.jpg").read_bytes() == b"custom"


def test_a_folder_holding_an_empty_folder_or_a_link_stays(root):
    with_folder = _folder(root, "a", "episode")
    (with_folder / "extras").mkdir()
    with_link = _folder(root, "b", "episode")
    (with_link / "link").symlink_to(root / "nowhere")

    assert remove_emptied_folders([with_folder, with_link], root=root) == []
    assert (with_folder / "extras").is_dir() and (with_link / "link").is_symlink()


def test_only_the_named_folders_and_their_parents_are_tried(root):
    episode = _folder(root, "show-slug", "episode")
    untouched = _folder(root, "other-show", "empty")

    remove_emptied_folders([episode], root=root)

    assert untouched.is_dir()


def test_the_root_and_everything_outside_it_stay(root):
    outside = root.parent / "outside"
    outside.mkdir()

    assert remove_emptied_folders([root, outside, root.parent, root / ".." / "outside"], root=root) == []
    assert root.is_dir() and outside.is_dir()


def test_a_sibling_whose_name_starts_like_the_root_is_outside(root):
    sibling = root.parent / (root.name + "-backup")
    sibling.mkdir()

    assert remove_emptied_folders([sibling], root=root) == []
    assert sibling.is_dir()


def test_kept_paths_and_the_folders_holding_them_stay_even_when_empty(root):
    old = _folder(root, "Video", "old")
    new = _folder(root, "Video", "new")
    own = _folder(root, ".vodloft-quick-downloads")

    removed = remove_emptied_folders([old, new, own], root=root, keep=[new / "episode.mp4", own])

    assert removed == [old]
    assert new.is_dir() and own.is_dir() and (root / "Video").is_dir()


def test_a_linked_folder_is_not_followed_or_removed(root):
    elsewhere = root.parent / "elsewhere"
    (elsewhere / "episode").mkdir(parents=True)
    (root / "show").symlink_to(elsewhere, target_is_directory=True)
    inside = _folder(root, "real")
    (root / "alias").symlink_to(inside, target_is_directory=True)

    assert remove_emptied_folders([root / "show" / "episode", root / "show", root / "alias"], root=root) == []
    assert (elsewhere / "episode").is_dir() and (root / "show").is_symlink() and (root / "alias").is_symlink()


def test_a_root_that_is_a_link_missing_relative_or_the_filesystem_root_removes_nothing(root):
    episode = _folder(root, "show", "episode")
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)

    assert remove_emptied_folders([alias / "show" / "episode"], root=alias) == []
    assert remove_emptied_folders([episode], root=root.parent / "missing") == []
    assert remove_emptied_folders([episode], root=Path("downloads")) == []
    assert remove_emptied_folders([episode], root=Path(root.anchor)) == []
    assert episode.is_dir()


def test_a_file_or_a_missing_path_is_left_alone(root):
    file = root / "show.mp4"
    file.write_bytes(b"media")

    assert remove_emptied_folders([file, root / "gone" / "deeper"], root=root) == []
    assert file.read_bytes() == b"media"


def test_nothing_but_rmdir_can_remove_anything(root, monkeypatch):
    """The guard of last resort: with every check passed, a folder with contents still cannot go."""
    episode = _folder(root, "show", "episode")
    (episode / "keep.txt").write_text("keep")
    monkeypatch.setattr(empty_folders, "_may_try", lambda *_: True)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("only os.rmdir may remove")

    for module, name in ((shutil, "rmtree"), (os, "unlink"), (os, "remove"), (os, "removedirs"), (Path, "unlink")):
        monkeypatch.setattr(module, name, forbidden)

    assert remove_emptied_folders([episode], root=root) == []
    assert (episode / "keep.txt").read_text() == "keep"


def test_the_module_never_deletes_files_or_whole_trees():
    source = Path(empty_folders.__file__).read_text()
    code = source.split('"""', 2)[2]

    for forbidden in ("rmtree", "unlink", "os.remove", "removedirs", "shutil", "walk", "iterdir", "scandir"):
        assert forbidden not in code


def _rename(library, template: str):  # noqa: F811
    from task_manager.tasks.workers.rename_collection_profile_files.service import (
        run_rename_collection_profile_files,
    )

    session, collection, source, _target_profile, _episodes, _downloads, root = library
    source.output_template = template
    session.commit()
    result = run_rename_collection_profile_files(collection_id=collection.id, local_media_profile_id=source.id)
    session.expire_all()
    return result, root


def test_a_profile_rename_removes_the_folders_it_emptied(library):  # noqa: F811
    result, root = _rename(library, "/downloads/Old/Renamed {{ collection }}/{{ title }}/{{ title }}.ext")

    assert result.data["files_renamed"] == 4
    assert not (root / "Old" / "Show").exists()
    assert (root / "Old" / "Renamed show" / "Episode 1" / "Episode 1.mp4").read_bytes() == b"Episode 1"


def test_a_profile_rename_keeps_a_folder_that_still_holds_a_file_of_the_user(library):  # noqa: F811
    root = library[-1]
    (root / "Old" / "Show" / ".notes").write_text("mine")

    result, root = _rename(library, "/downloads/New/{{ collection }}/{{ title }}.ext")

    assert result.data["files_renamed"] == 4
    assert (root / "Old" / "Show" / ".notes").read_text() == "mine"
    assert sorted(path.name for path in (root / "Old" / "Show").iterdir()) == [".notes"]


def test_a_rename_that_is_rolled_back_removes_no_folder(library, monkeypatch):  # noqa: F811
    from backend.services import download_relocation

    def fail(*_args, **_kwargs):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(download_relocation, "run_write_transaction", fail)
    session, collection, source, _target_profile, _episodes, downloads, root = library
    moves = [
        download_relocation.plan_download_relocation(
            download, Path(download.file_path), root / "New" / Path(download.file_path).name,
        )
        for download in downloads
    ]

    with pytest.raises(RuntimeError):
        download_relocation.relocate_downloads(moves)

    assert sorted(path.name for path in (root / "Old" / "Show").iterdir()) == [
        "Episode 1.mp4", "Episode 2.mp4", "Episode 3.mp4", "Episode 4.mp4",
    ]


def test_old_artwork_takes_its_emptied_folder_with_it(writer, monkeypatch):  # noqa: F811
    from config import get_settings
    from task_manager.tasks.workers.reconcile_collection_assets import service

    download_root = writer.plan.download_root.resolve()
    monkeypatch.setattr(get_settings().download_settings, "download_root", download_root)
    service._refresh_asset(writer.plan, _active)
    old = _target(writer)
    writer.current_root = old.parent.parent / "renamed collection"
    service._refresh_asset(replace(writer.plan, directory=writer.current_root), _active)
    writer.media_paths = [str(writer.current_root / "episode.mp4")]

    service._cleanup_old_roots(1, 1, writer.current_root, download_root, _active)

    assert not old.parent.exists()
    assert _target(writer).exists() and download_root.is_dir()


def test_old_artwork_leaves_a_folder_that_holds_something_else(writer, monkeypatch):  # noqa: F811
    from config import get_settings
    from task_manager.tasks.workers.reconcile_collection_assets import service

    download_root = writer.plan.download_root.resolve()
    monkeypatch.setattr(get_settings().download_settings, "download_root", download_root)
    service._refresh_asset(writer.plan, _active)
    old = _target(writer)
    (old.parent / "fanart-custom.jpg").write_bytes(b"mine")
    writer.current_root = old.parent.parent / "renamed collection"
    service._refresh_asset(replace(writer.plan, directory=writer.current_root), _active)
    writer.media_paths = [str(writer.current_root / "episode.mp4")]

    service._cleanup_old_roots(1, 1, writer.current_root, download_root, _active)

    assert not old.exists()
    assert (old.parent / "fanart-custom.jpg").read_bytes() == b"mine"


def _redownloaded_elsewhere(tmp_path, monkeypatch):
    from config import get_settings
    from downloader.storage.identity import inspect_artifact
    from downloader.storage.replacement import OwnedFile, PreviousDownload

    download_root = tmp_path.resolve()
    monkeypatch.setattr(get_settings().download_settings, "download_root", download_root)
    old = download_root / "Show" / "Old name" / "Episode.mp4"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old media")
    sidecar = old.with_suffix(".nfo")
    sidecar.write_bytes(b"<old />")
    new = download_root / "Show" / "New name" / "Episode.mp4"
    new.parent.mkdir()
    new.write_bytes(b"new media")
    previous = PreviousDownload(
        OwnedFile(old, inspect_artifact(old)), (OwnedFile(sidecar, inspect_artifact(sidecar)),),
    )
    execution = SimpleNamespace(result=SimpleNamespace(path=str(new)), assets=())
    return previous, execution, old, new


def test_a_redownload_under_a_new_name_removes_the_folder_it_emptied(tmp_path, monkeypatch):
    from task_manager.tasks import download_adapter

    previous, execution, old, new = _redownloaded_elsewhere(tmp_path, monkeypatch)

    download_adapter._retire_previous_after_commit(previous, execution)

    assert not old.parent.exists()
    assert new.read_bytes() == b"new media"


def test_a_redownload_keeps_the_old_folder_when_something_else_is_in_it(tmp_path, monkeypatch):
    from task_manager.tasks import download_adapter

    previous, execution, old, new = _redownloaded_elsewhere(tmp_path, monkeypatch)
    (old.parent / "my notes.txt").write_text("mine")

    download_adapter._retire_previous_after_commit(previous, execution)

    assert [path.name for path in old.parent.iterdir()] == ["my notes.txt"]
