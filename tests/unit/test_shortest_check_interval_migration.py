"""The shortest check interval of the YouTube API quota leaves config.yml."""
from __future__ import annotations

import importlib

migration = importlib.import_module(
    "backend.db.background_migrations.versions.bdf77aef4a9d_shortest_check_interval_leaves_config"
)


def test_only_the_shortest_check_interval_leaves_the_configuration():
    source = (
        "youtubeApi:\n"
        "  checksQuota: 7000  # keep this\n"
        "  minCheckIntervalMinutes: 30\n"
        "  searchQuota: 2000\n"
        "logLevel: INFO\n"
    )

    updated = migration._without_settings(source)

    assert updated == (
        "youtubeApi:\n"
        "  checksQuota: 7000  # keep this\n"
        "  searchQuota: 2000\n"
        "logLevel: INFO\n"
    )
    assert migration._without_settings(updated) == updated
