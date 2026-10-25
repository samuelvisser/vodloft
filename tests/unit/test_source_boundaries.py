"""Keep each Source's internals behind the Source contract.

Generic code reaches a service through ``sources`` (the contract and the
registry). Only the Daily Wire-only features below may still import
``sources.dailywire`` directly; they move behind the contract as later phases
need them, and an entry must be removed once its module stops importing it.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "server"

DAILYWIRE_FEATURE_MODULES = {
    "backend/src/backend/api/endpoints/dailywire/auth/router.py",
    "backend/src/backend/api/endpoints/dailywire/catalog/router.py",
    "backend/src/backend/api/endpoints/dailywire/catalog/service.py",
    "backend/src/backend/api/endpoints/dailywire/episodes/router.py",
    "backend/src/backend/api/endpoints/dailywire/episodes/service.py",
    "backend/src/backend/api/endpoints/dailywire/movies/router.py",
    "backend/src/backend/api/endpoints/dailywire/movies/service.py",
    "backend/src/backend/api/endpoints/dailywire/shows/router.py",
    "backend/src/backend/api/endpoints/dailywire/shows/service.py",
    "backend/src/backend/api/endpoints/dailywire/user_info/router.py",
    "backend/src/backend/api/endpoints/dailywire/user_info/service.py",
    "backend/src/backend/api/endpoints/feeds/service.py",
    "backend/src/backend/api/endpoints/media_downloads/service.py",
    "backend/src/backend/api/endpoints/movies/service.py",
    "backend/src/backend/db/background_migrations/versions/3c8f6a1d2b47_square_show_thumbnails.py",
    "backend/src/backend/db/background_migrations/versions/f6a1c3d8b427_episode_indexing_semantics.py",
    "backend/src/backend/services/movies.py",
    "backend/src/backend/services/show_assets.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/identifier.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/identifier_reconciliation.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/mapper.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/metadata.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/same_episode.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/save.py",
    "task_manager/src/task_manager/tasks/helpers/episodes/status.py",
    "task_manager/src/task_manager/tasks/helpers/seasons.py",
    "task_manager/src/task_manager/tasks/helpers/shows.py",
    "task_manager/src/task_manager/tasks/workers/debug_ep_details/service.py",
    "task_manager/src/task_manager/tasks/workers/fetch_new_episodes/service.py",
    "task_manager/src/task_manager/tasks/workers/monitor_no_usable_media_episode/service.py",
    "task_manager/src/task_manager/tasks/workers/monitor_pending_episode/_helpers.py",
    "task_manager/src/task_manager/tasks/workers/monitor_pending_episode/service.py",
    "task_manager/src/task_manager/tasks/workers/refresh_episode_metadata/service.py",
    "task_manager/src/task_manager/tasks/workers/refresh_movie_extras/service.py",
}


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
    return found


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _app_modules():
    for package in ("backend", "task_manager", "config", "controller", "downloader"):
        root = SERVER / package / "src"
        for path in root.rglob("*.py"):
            yield path.relative_to(SERVER).as_posix(), path


def test_only_daily_wire_features_import_daily_wire_internals():
    violations = [
        f"{name}:{line} imports {module}"
        for name, path in _app_modules()
        if name not in DAILYWIRE_FEATURE_MODULES
        for line, module in _imports(path)
        if _within(module, "sources.dailywire")
    ]
    assert violations == []


def test_daily_wire_feature_allowlist_has_no_stale_entries():
    importing = {
        name
        for name, path in _app_modules()
        if any(_within(module, "sources.dailywire") for _, module in _imports(path))
    }
    assert DAILYWIRE_FEATURE_MODULES - importing == set()


def test_downloader_does_not_know_about_sources():
    root = SERVER / "downloader" / "src"
    violations = [
        f"{path.relative_to(SERVER).as_posix()}:{line} imports {module}"
        for path in root.rglob("*.py")
        for line, module in _imports(path)
        if _within(module, "sources") or _within(module, "backend")
    ]
    assert violations == []


def test_sources_do_not_import_the_application():
    root = SERVER / "sources" / "src"
    violations = [
        f"{path.relative_to(SERVER).as_posix()}:{line} imports {module}"
        for path in root.rglob("*.py")
        for line, module in _imports(path)
        if any(_within(module, app) for app in ("backend", "task_manager", "controller"))
    ]
    assert violations == []
