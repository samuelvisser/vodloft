"""The no-usable-media schedule and deletion delay leave config.yml."""
from __future__ import annotations

import importlib

migration = importlib.import_module(
    "backend.db.background_migrations.versions.ecb0f787c77a_no_usable_media_settings_leave_config"
)


def test_only_the_no_usable_media_settings_leave_the_configuration():
    source = (
        "newEpisodeSchedule:\n"
        "  findEpisodesCron: '*/30 * * * *'  # keep this\n"
        "  monitorNoUsableMediaEpisodeCronEnabled: false\n"
        "  monitorNoUsableMediaEpisodeCron: '*/20 * * * *'\n"
        "episode_status_timing:\n"
        "  dw_processing_max_minutes: 60\n"
        "  no_usable_media_delete_after_minutes: 240\n"
        "logLevel: INFO\n"
    )

    updated = migration._without_settings(source)

    assert updated == (
        "newEpisodeSchedule:\n"
        "  findEpisodesCron: '*/30 * * * *'  # keep this\n"
        "episode_status_timing:\n"
        "  dw_processing_max_minutes: 60\n"
        "logLevel: INFO\n"
    )
    assert migration._without_settings(updated) == updated
