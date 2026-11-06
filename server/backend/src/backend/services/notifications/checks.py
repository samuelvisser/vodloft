"""Noticing problems: failed downloads, tasks that keep failing, a full disk, a Source that needs you, and updates."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Episode
from backend.db.models import NotificationEvent as EventRow
from backend.db.models.media_download import MediaDownloadBase
from backend.services.health import disk_space
from config import get_settings
from sources import all_sources
from task_manager.scheduler.db.TaskDefinition import TaskDefinition
from task_manager.scheduler.db.TaskRun import TaskRun
from task_manager.scheduler.types import TaskStatus

from .events import Event, emit

logger = logging.getLogger(__name__)

_DOWNLOAD_TASKS = ("download_episode", "download_movie")
_LOOK_BACK = timedelta(hours=2)
_FAILURES_IN_A_ROW = 3
_RELEASES_URL = "https://api.github.com/repos/samuelvisser/vodloft/releases/latest"
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def episode_url(episode: Episode) -> str:
    return f"/collection/{episode.collection.slug}/episode/{episode.slug}"


def _already(session: Session, event: Event, marker: str) -> bool:
    return session.scalar(select(EventRow.id).where(
        EventRow.event == event.value, EventRow.data["marker"].as_string() == marker,
    ).limit(1)) is not None


def failed_downloads(session: Session, now: datetime) -> int:
    """A download that failed after its retries."""
    runs = session.execute(
        select(TaskRun)
        .join(TaskDefinition, TaskDefinition.id == TaskRun.definition_id)
        .where(
            TaskDefinition.key.in_(_DOWNLOAD_TASKS), TaskRun.status == TaskStatus.FAILED,
            TaskRun.finished_at >= now - _LOOK_BACK,
        )
    ).scalars().all()
    emitted = 0
    for run in runs:
        marker = f"run:{run.id}"
        download = session.get(MediaDownloadBase, run.resource_id) if run.resource_id is not None else None
        if download is None or _already(session, Event.DOWNLOAD_FAILED, marker):
            continue
        media = download.media
        episode = media if isinstance(media, Episode) else None
        reason = (run.last_error or "").strip().splitlines()[0][:160] if run.last_error else "It failed"
        emit(
            session, Event.DOWNLOAD_FAILED, title=f"Download failed: {media.title}", body=reason,
            collection_id=episode.collection_id if episode else None,
            url=episode_url(episode) if episode else "/downloads",
            data={"marker": marker, "collection": episode.collection.title if episode else None, "episode": media.title},
            dedupe_key=f"download_failed:{episode.collection_id if episode else media.id}:{reason[:80]}",
            occurred_at=run.finished_at,
        )
        emitted += 1
    return emitted


def failing_tasks(session: Session, now: datetime) -> int:
    """A task whose last few runs all failed."""
    emitted = 0
    for definition in session.scalars(select(TaskDefinition).where(TaskDefinition.key.notin_(_DOWNLOAD_TASKS))):
        runs = session.scalars(
            select(TaskRun)
            .where(TaskRun.definition_id == definition.id, TaskRun.status.in_((TaskStatus.SUCCEEDED, TaskStatus.FAILED)))
            .order_by(TaskRun.finished_at.desc())
            .limit(_FAILURES_IN_A_ROW)
        ).all()
        if (
            len(runs) < _FAILURES_IN_A_ROW or any(run.status != TaskStatus.FAILED for run in runs)
            or runs[0].finished_at is None or runs[0].finished_at < now - _LOOK_BACK
        ):
            continue
        emit(
            session, Event.TASK_FAILING, title=f"{definition.title} keeps failing",
            body=(runs[0].last_error or "").strip()[:200], url="/tasks", dedupe_key=f"task:{definition.key}",
        )
        emitted += 1
    return emitted


def disk_check(session: Session) -> bool:
    disk = disk_space()
    minimum = get_settings().health.min_free_disk_mb * 1024 * 1024
    if disk is None or disk.free_bytes >= minimum:
        return False
    emit(
        session, Event.DISK_ALMOST_FULL, title="The disk is almost full",
        body=f"Only {disk.free_bytes / 1024 ** 3:.1f} GB is free in the download folder. Downloads will soon fail.",
        url="/settings?tab=downloads", dedupe_key="disk",
    )
    return True


def source_problems(session: Session) -> int:
    """A Source that needs you: a sign-in that expired, or a site that wants cookies."""
    emitted = 0
    for source in all_sources():
        try:
            problems = source.problems()
        except Exception:
            logger.debug("Could not ask %s for its problems", source.name, exc_info=True)
            continue
        for problem in problems:
            emit(
                session, Event.SIGN_IN_NEEDED, title=f"{source.name}: {problem.title}", body=problem.detail,
                url="/settings?tab=sources", dedupe_key=f"source:{source.id}:{problem.title}",
            )
            emitted += 1
    return emitted


def _version_tuple(text: str) -> tuple[int, int, int] | None:
    found = _VERSION.search(text)
    return tuple(int(part) for part in found.groups()) if found else None  # type: ignore[return-value]


def update_check(session: Session) -> bool:
    """A newer VODLoft release, told once per version."""
    try:
        current = _version_tuple(version("backend"))
    except PackageNotFoundError:
        return False
    try:
        response = requests.get(_RELEASES_URL, timeout=10, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        release = response.json()
    except (requests.RequestException, ValueError):
        return False
    tag = str(release.get("tag_name") or "")
    latest = _version_tuple(tag)
    if current is None or latest is None or latest <= current or _already(session, Event.UPDATE_AVAILABLE, tag):
        return False
    emit(
        session, Event.UPDATE_AVAILABLE, title=f"VODLoft {'.'.join(map(str, latest))} is out",
        body=str(release.get("name") or tag), url=str(release.get("html_url") or "") or None, data={"marker": tag},
    )
    return True


def run_checks(session: Session, *, now: datetime | None = None, include_slow: bool = False) -> None:
    """Every check; the slow ones, which ask outside services, only when asked."""
    now = now or datetime.now(timezone.utc)
    failed_downloads(session, now)
    session.commit()
    if not include_slow:
        return
    for check in (lambda: failing_tasks(session, now), lambda: disk_check(session), lambda: source_problems(session),
                  lambda: update_check(session)):
        try:
            check()
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("A notification check failed")
