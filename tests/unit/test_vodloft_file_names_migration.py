"""The background migration that renames the files WireLoft left in the download folders."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path

migration = importlib.import_module("backend.db.background_migrations.versions.2965d0593097_vodloft_file_names")


def _as_wireloft(root: Path) -> None:
    """Turn the files VODLoft wrote below ``root`` into the files WireLoft wrote."""
    for directory, folders, files in os.walk(root, topdown=False):
        parent = Path(directory)
        for name in files:
            path = parent / name
            contents = path.read_bytes()
            if contents.startswith(b"VODLOFT_"):
                path.write_bytes(b"WIRELOFT_" + contents.removeprefix(b"VODLOFT_"))
            elif b"vodloft-auxiliary-publication-v1" in contents:
                path.write_bytes(contents.replace(b"vodloft-auxiliary-publication-v1", b"wireloft-auxiliary-publication-v1"))
        for name in [*files, *folders]:
            if ".vodloft-" in name:
                os.rename(parent / name, parent / name.replace(".vodloft-", ".wireloft-", 1))


def _names(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


def test_wireloft_files_and_folders_get_vodloft_names(tmp_path):
    root = tmp_path / "downloads"
    (root / ".wireloft-index-locks").mkdir(parents=True)
    (root / ".wireloft-index-locks" / "show-1.lock").touch()
    (root / "Show" / "Episode.m3u8.assets").mkdir(parents=True)
    (root / "Show" / "Episode.m3u8.assets" / ".wireloft-hls-bundle").write_text("VODLoft local HLS bundle\n")
    (root / "Show" / ".Episode.mp4.wireloft-rename-abc.tmp").touch()
    (root / "Show" / "Episode.mp4").write_bytes(b"media")

    assert migration._rename_tree(root, configured=set()) == 3
    assert _names(root) == {
        ".vodloft-index-locks", ".vodloft-index-locks/show-1.lock",
        "Show", "Show/Episode.m3u8.assets", "Show/Episode.m3u8.assets/.vodloft-hls-bundle",
        "Show/.Episode.mp4.vodloft-rename-abc.tmp", "Show/Episode.mp4",
    }
    assert (root / "Show" / "Episode.mp4").read_bytes() == b"media"
    # Running it again finds nothing left to rename.
    assert migration._rename_tree(root, configured=set()) == 0


def test_a_folder_named_in_the_settings_keeps_its_name(tmp_path):
    root = tmp_path / "downloads"
    (root / ".wireloft-rss-cache").mkdir(parents=True)

    assert migration._rename_tree(root, configured={root / ".wireloft-rss-cache"}) == 0
    assert (root / ".wireloft-rss-cache").is_dir()


def test_nothing_is_replaced_by_a_rename(tmp_path):
    root = tmp_path / "downloads"
    (root / ".wireloft-index-locks").mkdir(parents=True)
    (root / ".vodloft-index-locks").mkdir()
    (root / ".vodloft-index-locks" / "kept.lock").touch()

    assert migration._rename_tree(root, configured=set()) == 0
    assert (root / ".wireloft-index-locks").is_dir()
    assert (root / ".vodloft-index-locks" / "kept.lock").exists()


def test_leftovers_of_an_interrupted_download_are_recovered_after_the_rename(tmp_path):
    from downloader.storage import (
        cleanup_abandoned_download_path_reservations,
        create_temporary_download_workspace,
        publish_temporary_download,
        reserve_unique_download_path,
    )
    from downloader.storage.temporary import _claim_publication_lock, cleanup_abandoned_temporary_downloads

    temporary_root, download_root = tmp_path / "temporary", tmp_path / "downloads"
    download_root.mkdir()
    reservation = reserve_unique_download_path(download_root / "Placeholder.m4a")
    lock = _claim_publication_lock(download_root / "Locked.m4a")
    workspace = create_temporary_download_workspace(temporary_root, download_root / "Published.m4a")
    workspace.path.write_bytes(b"complete media")
    published = publish_temporary_download(workspace.path, download_root / "Published.m4a")
    _as_wireloft(download_root)
    _as_wireloft(temporary_root)
    assert {name for name in _names(download_root) if "wireloft" in name}
    assert {name for name in _names(temporary_root) if "wireloft" in name}

    for root in (download_root, temporary_root):
        migration._rename_tree(root, configured=set())

    assert not {name for name in _names(download_root) | _names(temporary_root) if "wireloft" in name}
    assert cleanup_abandoned_download_path_reservations(download_root) == 2
    assert cleanup_abandoned_temporary_downloads(temporary_root, download_root, is_committed=lambda *_args: False) == 1
    assert not reservation.path.exists() and not reservation.marker_path.exists()
    assert not lock.path.exists()
    assert not published.exists()
    assert not workspace.workspace.exists()


def test_an_interrupted_auxiliary_publication_journal_gets_the_vodloft_format(tmp_path):
    journal = tmp_path / ".wireloft-auxiliary-publication"
    journal.write_text(json.dumps({"format": "wireloft-auxiliary-publication-v1", "entries": []}))

    migration._rename_tree(tmp_path, configured=set())

    record = json.loads((tmp_path / ".vodloft-auxiliary-publication").read_text())
    assert record == {"format": "vodloft-auxiliary-publication-v1", "entries": []}


def test_config_naming_the_old_secret_key_file_names_the_new_one():
    source = (
        "crypto:\n"
        "  # Keep this on a persistent volume.\n"
        "  defaultSecretFile: /config/wl_secret.key\n"
        "downloadSettings:\n"
        "  downloadMode: temporary\n"
    )

    updated, old_secret = migration._renamed_secret_file_setting(source)

    assert updated == source.replace("/config/wl_secret.key", "/config/vodloft_secret.key")
    assert old_secret == Path("/config/wl_secret.key")
    assert migration._renamed_secret_file_setting(updated) is None


def test_the_secret_key_file_and_config_are_renamed_together(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yml"
    old_secret = tmp_path / "wl_secret.key"
    old_secret.write_bytes(b"key")
    config_path.write_text(f"crypto:\n  defaultSecretFile: {old_secret}\n", encoding="utf-8")
    monkeypatch.setattr(migration, "get_config_path", lambda: config_path)
    reloads = []
    monkeypatch.setattr(migration, "reload_settings", lambda: reloads.append(True))

    migration._rename_secret_file()

    assert (tmp_path / "vodloft_secret.key").read_bytes() == b"key"
    assert not old_secret.exists()
    assert str(tmp_path / "vodloft_secret.key") in config_path.read_text(encoding="utf-8")
    assert reloads == [True]


def test_the_daily_wire_login_moves_to_the_vodloft_keyring_service(monkeypatch):
    from sources.dailywire.auth import DeviceAuthClient

    passwords = {("wireloft-dailywire-auth", "key"): "tokens"}
    monkeypatch.setattr(DeviceAuthClient, "__init__", lambda self: None)
    monkeypatch.setattr(DeviceAuthClient, "make_store_key", lambda self: "key")
    monkeypatch.setattr(migration.keyring, "get_password", lambda service, key: passwords.get((service, key)))
    monkeypatch.setattr(
        migration.keyring, "set_password", lambda service, key, value: passwords.__setitem__((service, key), value),
    )
    monkeypatch.setattr(migration.keyring, "delete_password", lambda service, key: passwords.pop((service, key)))

    migration._move_daily_wire_login()

    assert passwords == {("vodloft-dailywire-auth", "key"): "tokens"}


def test_the_migration_waits_for_the_startup_recovery(tmp_path, monkeypatch):
    import task_manager.scheduler.scheduler as scheduler_module
    from backend.services import download_recovery

    events = []
    held = iter([True, True, False])
    monkeypatch.setattr(scheduler_module, "scheduled_work_is_paused_by", lambda _owner: next(held))
    monkeypatch.setattr(migration, "_RECOVERY_POLL_SECONDS", 0)
    monkeypatch.setattr(migration, "_move_daily_wire_login", lambda: events.append("login"))
    monkeypatch.setattr(migration, "_rename_secret_file", lambda: events.append("secret"))
    monkeypatch.setattr(migration, "_rename_default_temporary_root", lambda: events.append("temporary root"))
    monkeypatch.setattr(migration, "_rename_tree", lambda root, configured: events.append("rename") or 0)
    monkeypatch.setattr(download_recovery, "recover_download_filesystem", lambda _settings: events.append("recover"))
    download_settings = migration.get_settings().download_settings
    monkeypatch.setattr(download_settings, "download_root", tmp_path / "downloads")
    monkeypatch.setattr(download_settings, "temporary_download_root", tmp_path / "temporary")
    (tmp_path / "downloads").mkdir()
    (tmp_path / "temporary").mkdir()

    class Context:
        def raise_if_cancelled(self):
            events.append("checked")

        def update_progress(self, current, total, message):
            pass

    asyncio.run(migration.migrate(Context()))

    work = [event for event in events if event != "checked"]
    assert work == ["login", "secret", "temporary root", "rename", "rename", "recover"]
    # It checked for cancellation while it waited.
    assert events.count("checked") >= 4


def test_the_old_default_temporary_folder_moves_to_the_new_default(tmp_path, monkeypatch):
    monkeypatch.setattr(migration.tempfile, "gettempdir", lambda: str(tmp_path))
    download_settings = migration.get_settings().download_settings
    monkeypatch.setattr(download_settings, "temporary_download_root", tmp_path / "vodloft-downloads")
    (tmp_path / "wireloft-downloads" / ".wireloft-staging").mkdir(parents=True)

    migration._rename_default_temporary_root()

    assert (tmp_path / "vodloft-downloads" / ".wireloft-staging").is_dir()
    assert not (tmp_path / "wireloft-downloads").exists()
