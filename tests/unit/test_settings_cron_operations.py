from __future__ import annotations


def test_settings_cron_operations_target_the_scheduled_workers():
    from backend.operations.settings import (
        FileWatcherCronOperation,
        FindEpisodesCronOperation,
        FullRescanCronOperation,
        MonitorNoUsableMediaCronOperation,
        QuickCheckCronOperation,
        VerifyDownloadsCronOperation,
    )

    cases = (
        (FindEpisodesCronOperation(), "fetch_new_episodes", "collection", None),
        (QuickCheckCronOperation(), "quick_check_new_videos", "system", 0),
        (FullRescanCronOperation(), "rescan_quick_checked_collections", "collection", None),
        (MonitorNoUsableMediaCronOperation(), "monitor_no_usable_media_episode", "collection", 0),
        (VerifyDownloadsCronOperation(), "download_profile_worker", "download_profile", 0),
        (FileWatcherCronOperation(), "file_watcher", "collection", 0),
    )

    for operation, task_key, resource_type, resource_id in cases:
        targets = operation.targets()
        assert len(targets) == 1
        target = targets[0]
        assert target.task_key == task_key
        assert target.resource_type == resource_type
        assert target.resource_id == resource_id


def test_running_the_pending_episode_monitor_now_looks_every_pending_episode_up():
    from backend.operations.settings import MonitorPendingEpisodesCronOperation

    operation = MonitorPendingEpisodesCronOperation()

    assert operation.resource_type == "system"
    assert operation.resource_id == 0
    assert [
        (target.task_key, target.resource_type, target.resource_id, target.task_kwargs)
        for target in operation.targets()
    ] == [("check_pending_episodes", "system", 0, {"monitor_everything": True})]


def test_settings_cron_operations_have_distinct_system_kinds():
    from backend.operations.settings import (
        FileWatcherCronOperation,
        FindEpisodesCronOperation,
        FullRescanCronOperation,
        MonitorNoUsableMediaCronOperation,
        MonitorPendingEpisodesCronOperation,
        QuickCheckCronOperation,
        VerifyDownloadsCronOperation,
    )

    operations = (
        FindEpisodesCronOperation(),
        QuickCheckCronOperation(),
        FullRescanCronOperation(),
        MonitorPendingEpisodesCronOperation(),
        MonitorNoUsableMediaCronOperation(),
        VerifyDownloadsCronOperation(),
        FileWatcherCronOperation(),
    )

    assert {operation.kind for operation in operations} == {
        "system.cron.find_episodes",
        "system.cron.quick_check",
        "system.cron.full_rescan",
        "system.cron.monitor_pending_episodes",
        "system.cron.monitor_no_usable_media",
        "system.cron.verify_downloads",
        "system.cron.file_watcher",
    }
