from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationTargetSpec


@dataclass(frozen=True)
class _SettingsCronResource:
    id: int
    title: str


class _SettingsCronOperation(OperationDefinition[_SettingsCronResource]):
    resource_type = "system"
    title_text: ClassVar[str]

    def __init__(self) -> None:
        super().__init__(_SettingsCronResource(id=0, title=self.title_text))


class _SingleTaskSettingsCronOperation(_SettingsCronOperation):
    task: ClassVar[str]
    target_resource_type: ClassVar[str]
    target_resource_id: ClassVar[int | None] = 0

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return (
            OperationTargetSpec(
                task_key=self.task,
                resource_type=self.target_resource_type,
                resource_id=self.target_resource_id,
            ),
        )


class FindEpisodesCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.find_episodes"
    title_text = "Find new episodes"
    task = "fetch_new_episodes"
    target_resource_type = "collection"
    target_resource_id = None


class QuickCheckCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.quick_check"
    title_text = "Quick check for new videos"
    task = "quick_check_new_videos"
    target_resource_type = "system"


class FullRescanCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.full_rescan"
    title_text = "Re-scan collections with quick checks"
    task = "rescan_quick_checked_collections"
    target_resource_type = "collection"
    target_resource_id = None


class MonitorNoUsableMediaCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.monitor_no_usable_media"
    title_text = "Monitor episodes without usable media"
    task = "monitor_no_usable_media_episode"
    target_resource_type = "collection"


class VerifyDownloadsCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.verify_downloads"
    title_text = "Verify downloads"
    task = "download_profile_worker"
    target_resource_type = "download_profile"


class FileWatcherCronOperation(_SingleTaskSettingsCronOperation):
    kind = "system.cron.file_watcher"
    title_text = "File watcher"
    task = "file_watcher"
    target_resource_type = "collection"
