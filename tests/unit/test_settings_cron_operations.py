from __future__ import annotations


def test_settings_cron_operations_target_the_scheduled_workers():
    from backend.operations.settings import (
        CollectionHealthCronOperation,
        FileWatcherCronOperation,
        FindEpisodesCronOperation,
        FullRescanCronOperation,
        QuickCheckCronOperation,
        VerifyDownloadsCronOperation,
    )

    cases = (
        (FindEpisodesCronOperation(), "fetch_new_episodes", "collection", None),
        (QuickCheckCronOperation(), "quick_check_new_videos", "system", 0),
        (FullRescanCronOperation(), "rescan_quick_checked_collections", "collection", None),
        (VerifyDownloadsCronOperation(), "download_profile_worker", "download_profile", 0),
        (FileWatcherCronOperation(), "file_watcher", "collection", 0),
        (CollectionHealthCronOperation(), "check_collection_health", "system", 0),
    )

    for operation, task_key, resource_type, resource_id in cases:
        targets = operation.targets()
        assert len(targets) == 1
        target = targets[0]
        assert target.task_key == task_key
        assert target.resource_type == resource_type
        assert target.resource_id == resource_id


def test_settings_cron_operations_have_distinct_system_kinds():
    from backend.operations.settings import (
        CollectionHealthCronOperation,
        FileWatcherCronOperation,
        FindEpisodesCronOperation,
        FullRescanCronOperation,
        QuickCheckCronOperation,
        VerifyDownloadsCronOperation,
    )

    operations = (
        FindEpisodesCronOperation(),
        QuickCheckCronOperation(),
        FullRescanCronOperation(),
        VerifyDownloadsCronOperation(),
        FileWatcherCronOperation(),
        CollectionHealthCronOperation(),
    )

    assert {operation.kind for operation in operations} == {
        "system.cron.find_episodes",
        "system.cron.quick_check",
        "system.cron.full_rescan",
        "system.cron.verify_downloads",
        "system.cron.file_watcher",
        "system.cron.collection_health",
    }
