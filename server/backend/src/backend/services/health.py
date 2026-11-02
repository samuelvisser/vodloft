"""Whether VODLoft is working, for Docker's health check and for Prometheus.

VODLoft is healthy when its database answers and its scheduler runs. Little
free space in the download folder is reported as a warning: VODLoft still
works, but downloads will soon fail.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from config import get_settings
from task_manager.scheduler.db.TaskRun import TaskRun
from task_manager.scheduler.scheduler import scheduler_running

from backend.db.models import Collection
from backend.db.models.media_download import MediaDownloadBase
from backend.db.models.media_item import Episode

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


class HealthStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: HealthStatus
    detail: str


@dataclass(frozen=True)
class DiskSpace:
    free_bytes: int
    total_bytes: int


@dataclass(frozen=True)
class Health:
    status: HealthStatus
    version: str
    checks: list[HealthCheck]
    disk: DiskSpace | None

    @property
    def healthy(self) -> bool:
        return self.status is not HealthStatus.ERROR


def _database(session: Session) -> HealthCheck:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Health check: the database does not answer: %s", exc)
        return HealthCheck("database", HealthStatus.ERROR, "The database does not answer")
    return HealthCheck("database", HealthStatus.OK, "The database answers")


def _scheduler() -> HealthCheck:
    if scheduler_running():
        return HealthCheck("scheduler", HealthStatus.OK, "The scheduler runs")
    return HealthCheck("scheduler", HealthStatus.ERROR, "The scheduler is not running")


def disk_space() -> DiskSpace | None:
    """Free and total space of the filesystem that holds the download folder."""
    try:
        usage = shutil.disk_usage(get_settings().download_settings.download_root)
    except OSError:
        return None
    return DiskSpace(free_bytes=usage.free, total_bytes=usage.total)


def _disk(disk: DiskSpace | None) -> HealthCheck:
    if disk is None:
        return HealthCheck("disk", HealthStatus.ERROR, "The download folder cannot be read")
    minimum = get_settings().health.min_free_disk_mb * _MB
    free = f"{disk.free_bytes / (1024 * _MB):.1f} GB free in the download folder"
    if disk.free_bytes < minimum:
        return HealthCheck("disk", HealthStatus.WARNING, f"Only {free}")
    return HealthCheck("disk", HealthStatus.OK, free[0].upper() + free[1:])


def check_health(session: Session) -> Health:
    disk = disk_space()
    checks = [_database(session), _scheduler(), _disk(disk)]
    statuses = {check.status for check in checks}
    status = next(
        (level for level in (HealthStatus.ERROR, HealthStatus.WARNING) if level in statuses), HealthStatus.OK,
    )
    return Health(status=status, version=get_settings().app_version, checks=checks, disk=disk)


def _labels(**labels: str) -> str:
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")

    return "{" + ",".join(f'{key}="{escape(value)}"' for key, value in labels.items()) + "}" if labels else ""


def metrics_text(session: Session) -> str:
    """The health check and a few counts in Prometheus' text format."""
    health = check_health(session)
    lines: list[str] = []

    def metric(name: str, kind: str, help_text: str, samples: list[tuple[dict[str, str], float]]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.extend(f"{name}{_labels(**labels)} {value:g}" for labels, value in samples)

    metric("vodloft_info", "gauge", "The running VODLoft version.", [({"version": health.version}, 1)])
    metric("vodloft_healthy", "gauge", "1 when VODLoft's health check passes.", [({}, int(health.healthy))])
    metric(
        "vodloft_health_check", "gauge", "1 when a part of the health check is ok, 0.5 for a warning, 0 for an error.",
        [({"check": check.name}, {HealthStatus.OK: 1, HealthStatus.WARNING: 0.5}.get(check.status, 0))
         for check in health.checks],
    )
    if health.disk is not None:
        metric("vodloft_disk_free_bytes", "gauge", "Free space in the download folder.", [({}, health.disk.free_bytes)])
        metric("vodloft_disk_total_bytes", "gauge", "Size of the download folder's filesystem.", [({}, health.disk.total_bytes)])
    metric(
        "vodloft_collections", "gauge", "Collections in the library, per Source.",
        [({"source": source}, count) for source, count in session.execute(
            select(Collection.source_key, func.count()).group_by(Collection.source_key).order_by(Collection.source_key)
        )],
    )
    metric(
        "vodloft_episodes", "gauge", "Indexed episodes, per Source.",
        [({"source": source}, count) for source, count in session.execute(
            select(Episode.source_key, func.count()).group_by(Episode.source_key).order_by(Episode.source_key)
        )],
    )
    metric(
        "vodloft_downloads", "gauge", "Download records, per state of their file.",
        [({"state": state}, count) for state, count in session.execute(
            select(MediaDownloadBase.artifact_status, func.count())
            .group_by(MediaDownloadBase.artifact_status).order_by(MediaDownloadBase.artifact_status)
        )],
    )
    metric(
        "vodloft_tasks", "gauge", "Tasks, per status.",
        [({"status": str(getattr(status, "value", status))}, count) for status, count in session.execute(
            select(TaskRun.status, func.count()).group_by(TaskRun.status).order_by(TaskRun.status)
        )],
    )
    return "\n".join(lines) + "\n"
