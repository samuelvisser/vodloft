"""Startup removes the folders VODLoft managed under a folder setting that has since changed."""
from __future__ import annotations

import json

import pytest

from backend.services import retired_folders
from config.settings.submodels import DownloadSettings


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    monkeypatch.setenv("VL_CONFIG_FILE", str(directory / "config.yml"))
    return directory


def _settings(tmp_path, **folders) -> DownloadSettings:
    downloads = tmp_path / "downloads"
    downloads.mkdir(exist_ok=True)
    return DownloadSettings(
        download_root=downloads,
        temporary_download_root=folders.pop("temporary_download_root", tmp_path / "local" / "vodloft-downloads"),
        **folders,
    )


def test_the_first_start_only_remembers_the_folders(tmp_path, config_dir):
    settings = _settings(tmp_path)

    assert retired_folders.retire_changed_folders(settings) == 0
    stored = json.loads((config_dir / "folders.json").read_text())
    assert stored["lock_root"] == str(config_dir / "locks")
    assert stored["rss_cache_root"] == str(tmp_path / "downloads" / ".vodloft-rss-cache")


def test_a_hidden_vodloft_folder_goes_after_its_setting_changes(tmp_path, config_dir):
    old = tmp_path / "downloads" / ".vodloft-temp"
    retired_folders.retire_changed_folders(_settings(tmp_path, temporary_download_root=old))
    (old / ".vodloft-staging").mkdir(parents=True)
    (tmp_path / "downloads" / "Show").mkdir()

    assert retired_folders.retire_changed_folders(_settings(tmp_path)) == 1
    assert not old.exists()
    assert (tmp_path / "downloads" / "Show").is_dir()
    # It is not tried again.
    assert "retired:temporary_download_root" not in json.loads((config_dir / "folders.json").read_text())


def test_a_folder_of_the_users_own_stays(tmp_path, config_dir):
    own = tmp_path / "my-locks"
    retired_folders.retire_changed_folders(_settings(tmp_path, lock_root=own))
    own.mkdir()
    (own / "notes.txt").write_text("mine")

    assert retired_folders.retire_changed_folders(_settings(tmp_path)) == 0
    assert (own / "notes.txt").read_text() == "mine"


def test_the_default_lock_folder_goes_when_locks_move(tmp_path, config_dir):
    retired_folders.retire_changed_folders(_settings(tmp_path))
    (config_dir / "locks" / "assets").mkdir(parents=True)
    (config_dir / "config.yml").write_text("")

    assert retired_folders.retire_changed_folders(_settings(tmp_path, lock_root=tmp_path / "elsewhere")) == 1
    assert not (config_dir / "locks").exists()
    assert (config_dir / "config.yml").exists()


def test_thumbnails_move_to_the_new_folder(tmp_path, config_dir):
    old = tmp_path / "downloads" / ".vodloft-thumbnails"
    new = tmp_path / "thumbs"
    retired_folders.retire_changed_folders(_settings(tmp_path))
    old.mkdir()
    (old / "frame.jpg").write_bytes(b"jpg")

    assert retired_folders.retire_changed_folders(_settings(tmp_path, thumbnail_root=new)) == 1
    assert not old.exists()
    assert (new / "frame.jpg").read_bytes() == b"jpg"


def test_a_former_folder_that_holds_a_current_one_stays(tmp_path, config_dir):
    old = tmp_path / "downloads" / ".vodloft-cache"
    retired_folders.retire_changed_folders(_settings(tmp_path, rss_cache_root=old))
    old.mkdir()

    settings = _settings(tmp_path, rss_cache_root=old / "rss", lock_root=old / "locks")
    assert retired_folders.retire_changed_folders(settings) == 0
    assert old.is_dir()


def test_a_former_folder_that_holds_the_download_root_stays(tmp_path, config_dir):
    outer = tmp_path / ".vodloft-outer"
    downloads = outer / "downloads"
    downloads.mkdir(parents=True)
    settings = DownloadSettings(download_root=downloads, temporary_download_root=tmp_path / "local")
    retired_folders.retire_changed_folders(settings)
    retired_folders._store_state({"rss_cache_root": str(outer)})

    assert retired_folders.retire_changed_folders(settings) == 0
    assert downloads.is_dir()
