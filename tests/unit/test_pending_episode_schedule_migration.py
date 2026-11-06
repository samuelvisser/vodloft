"""The "Monitor pending episodes" schedule leaves config.yml."""
from __future__ import annotations

import asyncio
import importlib

migration = importlib.import_module(
    "backend.db.background_migrations.versions.7f51410a2578_pending_episode_schedule_leaves_config"
)


def test_only_the_monitor_schedule_leaves_the_configuration():
    source = (
        "newEpisodeSchedule:\n"
        "  findEpisodesCron: '*/30 * * * *'  # keep this\n"
        "  monitorPendingEpisodeCronEnabled: false\n"
        "  monitorPendingEpisodeCron: '*/3 * * * *'\n"
        "  monitorNoUsableMediaEpisodeCron: '*/20 * * * *'\n"
        "logLevel: INFO\n"
    )

    updated = migration._without_monitor_schedule(source)

    assert updated == (
        "newEpisodeSchedule:\n"
        "  findEpisodesCron: '*/30 * * * *'  # keep this\n"
        "  monitorNoUsableMediaEpisodeCron: '*/20 * * * *'\n"
        "logLevel: INFO\n"
    )
    assert migration._without_monitor_schedule(updated) == updated


def test_the_schedule_is_removed_once_also_in_snake_case(tmp_path, monkeypatch):
    path = tmp_path / "config.yml"
    path.write_text("new_episode_schedule:\n  monitor_pending_episode_cron: '*/2 * * * *'\n", encoding="utf-8")
    monkeypatch.setattr(migration, "get_config_path", lambda: path)
    reloads = []
    monkeypatch.setattr(migration, "reload_settings", lambda: reloads.append(True))

    class Context:
        def raise_if_canceled(self):
            pass

    asyncio.run(migration.migrate(Context()))
    assert path.read_text(encoding="utf-8") == "new_episode_schedule:\n"
    assert reloads == [True]

    asyncio.run(migration.migrate(Context()))
    assert reloads == [True]
