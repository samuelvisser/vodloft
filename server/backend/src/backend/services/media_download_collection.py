"""Composable SQL for media-download collection status, filtering and ordering.

The helpers in this module build SQLAlchemy expressions and statements rather
than materializing rows. API code remains responsible for cursor validation and
hydrating the small page of ORM objects returned by these queries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone
from hashlib import blake2b

from sqlalchemy import String, and_, case, exists, func, literal, or_, select, type_coerce
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import CTE, Subquery

from backend.db.json_sql import json_array_items
from backend.db.models import MediaDownloadBase
from backend.db.models.media_item import MediaItemBase
from backend.services.media_access import locked_clause
from backend.types.download_profile_types import MediaDownloadArtifactStatus
from task_manager.scheduler.db import (
    TaskDefinition,
    TaskOperation,
    TaskOperationRun,
    TaskRun,
)
from task_manager.scheduler.types import OperationStatus, ResourceType, TaskStatus
from task_manager.tasks.media_download_operations import (
    media_download_queue_position_subquery,
)


_MEDIA_DOWNLOAD_TASK_KEYS = ("download_episode", "download_movie")

_ACTIVE_DOWNLOAD_STATUSES = (
    OperationStatus.QUEUED,
    OperationStatus.RUNNING,
    OperationStatus.WAITING,
)
_ACTIVE_WORKFLOW_STATUSES = (
    "downloading",
    "preparing",
    "waiting",
    "canceling",
    "local_processing",
)
# Retry all leaves finished downloads alone: re-downloading a whole library by
# accident is costly, so a finished download is only retried on its own row.
_BULK_RETRYABLE_STATUSES = (
    "preparing",
    "waiting",
    "downloading",
    "local_processing",
    "error",
    "missing",
    "corrupted",
    "canceled",
)
_MEDIA = aliased(MediaItemBase, name="download_media")
"""The download's media, for whether a Source locked it."""
_CANCELABLE_STATUSES = (
    "pending",
    "preparing",
    "waiting",
    "downloading",
    "local_processing",
)


def _latest_download_run_ids(
    media_download_ids: Sequence[int] | None = None,
) -> Subquery:
    """Latest download TaskRun IDs, optionally narrowed to one page of downloads."""
    statement = (
        select(
            TaskRun.resource_id.label("media_download_id"),
            func.max(TaskRun.id).label("run_id"),
        )
        .join(TaskDefinition, TaskDefinition.id == TaskRun.definition_id)
        .where(
            TaskRun.resource_type == ResourceType.MEDIA_DOWNLOAD,
            TaskDefinition.key.in_(_MEDIA_DOWNLOAD_TASK_KEYS),
        )
        .group_by(TaskRun.resource_id)
    )
    if media_download_ids is not None:
        statement = statement.where(
            TaskRun.resource_id.in_(media_download_ids)
        )
    return statement.subquery()


def latest_download_runs(
    session: Session,
    media_download_ids: Sequence[int],
) -> dict[int, TaskRun]:
    """Hydrate only the latest TaskRuns needed by one rendered download page."""
    if not media_download_ids:
        return {}

    latest_ids = _latest_download_run_ids(media_download_ids)
    runs = session.scalars(
        select(TaskRun).join(
            latest_ids,
            TaskRun.id == latest_ids.c.run_id,
        )
    )
    return {
        int(run.resource_id): run
        for run in runs
        if run.resource_id is not None
    }


def media_download_queue_positions(
    session: Session,
    media_download_ids: Sequence[int],
) -> dict[int, int]:
    """Read global queue positions only for the downloads being rendered."""
    if not media_download_ids:
        return {}

    queue = media_download_queue_position_subquery()
    return {
        int(media_download_id): int(queue_position)
        for media_download_id, queue_position in session.execute(
            select(
                queue.c.media_download_id,
                queue.c.queue_position,
            )
            .where(queue.c.media_download_id.in_(media_download_ids))
            .order_by(queue.c.queue_position)
        )
    }


def _latest_active_download_operation_ids() -> Subquery:
    """The newest active media.download operation of each MediaDownload, by id.

    Grouped by download, so SQLite knows each download appears once and indexes the
    result when it joins it. Without that it can guess the active operations are a few
    rows and scan them all for every download: with thousands of downloads queued, the
    Downloads page then took minutes to load.
    """
    ranked = (
        select(
            TaskOperation.resource_id.label("media_download_id"),
            TaskOperation.id.label("operation_id"),
            func.row_number().over(
                partition_by=TaskOperation.resource_id,
                order_by=(
                    TaskOperation.created_at.desc(),
                    TaskOperation.id.desc(),
                ),
            ).label("operation_rank"),
        )
        .where(
            TaskOperation.kind == "media.download",
            TaskOperation.resource_type == ResourceType.MEDIA_DOWNLOAD.value,
            TaskOperation.resource_id.is_not(None),
            TaskOperation.status.in_(_ACTIVE_DOWNLOAD_STATUSES),
        )
        .subquery()
    )
    return (
        select(ranked.c.media_download_id, func.max(ranked.c.operation_id).label("operation_id"))
        .where(ranked.c.operation_rank == 1)
        .group_by(ranked.c.media_download_id)
        .subquery()
    )


@dataclass(frozen=True)
class _ActiveOperation:
    """The columns of a download's newest active operation, joined by its primary key."""

    operation_id: Any
    operation_status: Any
    operation_context: Any
    operation_started_at: Any
    operation_created_at: Any
    operation_admitted: Any

    @classmethod
    def of(cls, operation) -> "_ActiveOperation":
        return cls(
            operation_id=operation.id,
            operation_status=operation.status,
            operation_context=operation.context,
            operation_started_at=operation.started_at,
            operation_created_at=operation.created_at,
            operation_admitted=exists(
                select(TaskOperationRun.task_run_id).where(
                    TaskOperationRun.operation_id == operation.id,
                )
            ),
        )


def _download_is_canceling(active_operation, progress_meta, execution):
    return or_(
        func.coalesce(
            active_operation.operation_context["cancel_requested"].as_boolean(),
            False,
        ).is_(True),
        func.coalesce(progress_meta["canceling"].as_boolean(), False).is_(True),
        func.coalesce(execution["canceling"].as_boolean(), False).is_(True),
    )


def _main_download_stage_is_waiting(execution):
    stages = json_array_items(TaskRun.meta, "_progress_meta", "download", "stages").alias("download_stage")
    return exists(
        select(literal(1)).select_from(stages).where(
            stages.c.value["id"].as_string() == execution["main_activity"].as_string(),
            stages.c.value[("wait", "reason")].as_string().is_not(None),
        )
    )


def _download_is_waiting(active_operation, progress_meta, execution):
    return or_(
        active_operation.operation_status == OperationStatus.WAITING.value,
        _main_download_stage_is_waiting(execution),
        progress_meta["wait_state"]["reason"].as_string().is_not(None),
    )


def _download_is_transferring(execution):
    return and_(
        execution["phase"].as_string() == "transferring",
        execution["main_activity"].as_string() == "media",
    )


def _download_primary_transfer_is_complete(execution):
    return func.coalesce(
        execution["primary_transfer_complete"].as_boolean(),
        False,
    ).is_(True)


def _download_run_is_redownload():
    return func.coalesce(
        TaskRun.meta["inputs"]["is_redownload"].as_boolean(),
        TaskRun.result["data"]["is_redownload"].as_boolean(),
        False,
    )


def _active_download_status(active_operation, progress_meta, execution):
    """UI status while an active media.download operation owns the download."""
    return case(
        (
            _download_is_canceling(active_operation, progress_meta, execution),
            "canceling",
        ),
        (
            active_operation.operation_status == OperationStatus.QUEUED.value,
            "pending",
        ),
        (
            _download_is_waiting(active_operation, progress_meta, execution),
            "waiting",
        ),
        (_download_is_transferring(execution), "downloading"),
        (
            _download_primary_transfer_is_complete(execution),
            "local_processing",
        ),
        else_="preparing",
    )


def _persistent_download_status():
    """UI status when no active media.download operation owns the download."""
    return case(
        (
            MediaDownloadBase.artifact_status
            == MediaDownloadArtifactStatus.AVAILABLE.value,
            case(
                (_download_run_is_redownload().is_(True), "redownloaded"),
                else_="downloaded",
            ),
        ),
        (
            MediaDownloadBase.artifact_status
            == MediaDownloadArtifactStatus.MISSING.value,
            "missing",
        ),
        (
            MediaDownloadBase.artifact_status
            == MediaDownloadArtifactStatus.CORRUPTED.value,
            "corrupted",
        ),
        (TaskRun.status == TaskStatus.RUNNING, "preparing"),
        # Media the Source keeps for members or subscribers is not an error.
        (locked_clause(_MEDIA), "locked"),
        (TaskRun.status == TaskStatus.FAILED, "error"),
        (
            or_(
                MediaDownloadBase.automatic_retry_suppressed.is_(True),
                TaskRun.status == TaskStatus.CANCELED,
            ),
            "canceled",
        ),
        else_="not_downloaded",
    )


def _effective_download_status(active_operation):
    progress_meta = TaskRun.meta["_progress_meta"]
    execution = progress_meta["download"]
    return case(
        (
            active_operation.operation_id.is_not(None),
            _active_download_status(
                active_operation,
                progress_meta,
                execution,
            ),
        ),
        else_=_persistent_download_status(),
    ).label("status")


def _awaiting_admission(active_operation):
    """Whether the download waits before admission, such as a publication delay.

    These operations have not claimed a download slot and no worker has
    started, unlike runs that report a wait while they execute.
    """
    return func.coalesce(and_(
        active_operation.operation_status == OperationStatus.WAITING.value,
        active_operation.operation_admitted.is_(False),
    ), False).label("awaiting_admission")


def _download_status_source() -> CTE:
    """One SQL relation containing the effective UI status for every download.

    Materialized, so the database works each status out once. Inlined, the status
    expression was copied into every sort key that uses it, and PostgreSQL parsed
    each download's task run JSON again for every copy: several seconds a page.
    """
    latest_run_ids = _latest_download_run_ids()
    active_operation_ids = _latest_active_download_operation_ids()
    operation = aliased(TaskOperation, name="active_operation")
    active_operation = _ActiveOperation.of(operation)
    queue = media_download_queue_position_subquery()
    # Delayed downloads sort where they will dispatch once their wait ends.
    sort_queue = media_download_queue_position_subquery(include_admission_waits=True)

    return (
        select(
            MediaDownloadBase.id.label("id"),
            MediaDownloadBase.artifact_status.label("artifact_status"),
            MediaDownloadBase.downloaded_at.label("downloaded_at"),
            MediaDownloadBase.created_at.label("created_at"),
            MediaDownloadBase.updated_at.label("updated_at"),
            TaskRun.finished_at.label("run_finished_at"),
            TaskRun.status.label("run_status"),
            TaskRun.started_at.label("run_started_at"),
            TaskRun.created_at.label("run_created_at"),
            active_operation.operation_started_at.label("operation_started_at"),
            active_operation.operation_created_at.label("operation_created_at"),
            queue.c.queue_position.label("queue_position"),
            sort_queue.c.queue_position.label("sort_queue_position"),
            _awaiting_admission(active_operation),
            _effective_download_status(active_operation),
        )
        .outerjoin(_MEDIA, _MEDIA.id == MediaDownloadBase.media_item_id)
        .outerjoin(
            latest_run_ids,
            latest_run_ids.c.media_download_id == MediaDownloadBase.id,
        )
        .outerjoin(TaskRun, TaskRun.id == latest_run_ids.c.run_id)
        .outerjoin(
            active_operation_ids,
            active_operation_ids.c.media_download_id == MediaDownloadBase.id,
        )
        .outerjoin(operation, operation.id == active_operation_ids.c.operation_id)
        .outerjoin(
            queue,
            queue.c.media_download_id == MediaDownloadBase.id,
        )
        .outerjoin(
            sort_queue,
            sort_queue.c.media_download_id == MediaDownloadBase.id,
        )
        .cte("download_status")
        .prefix_with("MATERIALIZED")
    )


def _recent_activity_at(status_source):
    return case(
        (
            status_source.c.status.in_(("downloaded", "redownloaded")),
            func.coalesce(
                status_source.c.run_finished_at,
                status_source.c.downloaded_at,
                status_source.c.created_at,
            ),
        ),
        else_=func.coalesce(
            status_source.c.run_finished_at,
            status_source.c.updated_at,
            status_source.c.created_at,
        ),
    ).label("recent_at")


def _is_executing(status_source):
    return and_(
        status_source.c.status.in_(_ACTIVE_WORKFLOW_STATUSES),
        status_source.c.awaiting_admission.is_(False),
    )


def _is_queued(status_source):
    return or_(
        status_source.c.status == "pending",
        status_source.c.awaiting_admission.is_(True),
    )


def _workflow_bucket(status_source):
    """Running work, then the dispatch queue, then the rest.

    Admission waits (publication delay, countdown) have not started yet, so
    they belong to the queue rather than to downloads that are executing.
    """
    return case(
        (_is_executing(status_source), 0),
        (_is_queued(status_source), 1),
        else_=2,
    ).label("workflow_bucket")


def _workflow_active_started_at(status_source):
    """Sort in-progress downloads by this execution's start, oldest first.

    Ignore finished runs from previous attempts when an operation is waiting
    without a current TaskRun. Other workflow buckets use a constant key.
    """
    current_run_started_at = case(
        (
            status_source.c.run_status.in_((
                TaskStatus.SCHEDULED,
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.RETRY_SCHEDULED,
            )),
            func.coalesce(
                status_source.c.run_started_at,
                status_source.c.run_created_at,
            ),
        ),
    )
    return case(
        (
            _is_executing(status_source),
            func.coalesce(
                current_run_started_at,
                status_source.c.operation_started_at,
                status_source.c.operation_created_at,
                status_source.c.created_at,
            ),
        ),
        else_=datetime(1970, 1, 1, tzinfo=timezone.utc),
    ).label("workflow_active_started_at")


def _workflow_terminal_at(status_source):
    """Sort all non-active, non-queued downloads by their latest state change.

    Successful transfers have a dedicated completion timestamp. Failed and
    canceled attempts use the latest task's finish time, including when the
    MediaDownload row itself did not change. Artifact-only states have no
    dedicated transition timestamp, so use the record's last modification.
    Active and queued buckets keep a constant key.
    """
    return case(
        (
            status_source.c.status.in_(("downloaded", "redownloaded")),
            func.coalesce(
                status_source.c.downloaded_at,
                status_source.c.run_finished_at,
                status_source.c.created_at,
            ),
        ),
        (
            status_source.c.status.in_(("error", "locked", "canceled")),
            func.coalesce(
                status_source.c.run_finished_at,
                status_source.c.updated_at,
                status_source.c.created_at,
            ),
        ),
        (
            status_source.c.status.not_in(
                (*_ACTIVE_WORKFLOW_STATUSES, "pending")
            ),
            func.coalesce(
                status_source.c.updated_at,
                status_source.c.created_at,
            ),
        ),
        else_=datetime(1970, 1, 1, tzinfo=timezone.utc),
    ).label("workflow_terminal_at")


def _workflow_queue_position(status_source):
    """Dispatcher order, with admission waits at the place they will take."""
    return case(
        (
            _is_queued(status_source),
            func.coalesce(status_source.c.sort_queue_position, -1),
        ),
        else_=0,
    ).label("workflow_queue")


def _collection_source() -> Subquery:
    """Projection used by paging, facets and bulk actions.

    Every helper above contributes SQL expressions only. Building this relation
    performs no database I/O; SQLAlchemy folds the concepts into the statement
    executed by the caller.
    """
    status_source = _download_status_source()
    return (
        select(
            status_source,
            _recent_activity_at(status_source),
            _workflow_bucket(status_source),
            _workflow_queue_position(status_source),
            _workflow_active_started_at(status_source),
            _workflow_terminal_at(status_source),
        )
        .subquery()
    )


MEDIA_DOWNLOAD_BULK_ACTIONS = ("retry", "cancel", "delete-unavailable")

_UNAVAILABLE_ARTIFACT_STATUSES = (
    MediaDownloadArtifactStatus.ABSENT,
    MediaDownloadArtifactStatus.MISSING,
)


def supports_bulk_action(action: str, status: str, artifact_status: str) -> bool:
    """Whether a download with this status and file state takes part in a bulk action."""
    if action == "retry":
        return status in _BULK_RETRYABLE_STATUSES
    if action == "cancel":
        return status in _CANCELABLE_STATUSES
    if action == "delete-unavailable":
        return artifact_status in _UNAVAILABLE_ARTIFACT_STATUSES
    raise ValueError(f"Unknown media download bulk action: {action}")


@dataclass(frozen=True)
class MediaDownloadCollectionQuery:
    """Composable SQL statements for the mutable media-download collection."""

    source: Subquery

    @classmethod
    def build(cls) -> "MediaDownloadCollectionQuery":
        return cls(source=_collection_source())

    def _ordering(self, order: str):
        if order == "recent":
            return (
                self.source.c.recent_at.desc(),
                self.source.c.id.desc(),
            )
        return (
            self.source.c.workflow_bucket.asc(),
            self.source.c.workflow_queue.asc(),
            self.source.c.workflow_active_started_at.asc(),
            self.source.c.workflow_terminal_at.desc(),
            self.source.c.id.desc(),
        )

    def walk_statement(self, *, order: str | None):
        """Every download in page order, with what a page counts and shows of it.

        Working out the statuses is the expensive part, so a page reads them once,
        here, and counts, filters and fingerprints the result in Python.
        """
        statement = select(
            self.source.c.id,
            self.source.c.status,
            self.source.c.artifact_status,
            self.source.c.queue_position,
        )
        return statement.order_by(*self._ordering(order)) if order else statement


@dataclass(frozen=True)
class MediaDownloadPageWindow:
    """What one page of the filtered collection shows, from a single walk over it."""

    rows: list[Any]
    """Up to ``limit + 1`` rows, the extra one only telling that more follow."""
    facets: dict[str, int]
    total: int
    actions: dict[str, int]
    revision: str
    """Fingerprint of the membership and order of the filtered collection.

    Execution progress, statuses and timestamps matter only if they change the
    ordered sequence of matching IDs.
    """


def read_media_download_page_window(
    session: Session,
    *,
    statuses: Sequence[str],
    order: str,
    limit: int,
    after_id: int | None = None,
    after_revision: str | None = None,
) -> MediaDownloadPageWindow:
    """Count, filter, fingerprint and page the downloads in one ordered pass.

    The page continues after ``after_id`` only while the collection still has the
    ``after_revision`` it had then; otherwise it starts again from the top. Raises
    ``LookupError`` when the revision matches but ``after_id`` is not in it.
    """
    wanted = set(statuses)
    facets: dict[str, int] = {}
    actions = dict.fromkeys(MEDIA_DOWNLOAD_BULK_ACTIONS, 0)
    total = 0
    digest = blake2b(digest_size=16)
    first: list[Any] = []
    following: list[Any] = []
    passed_after = False

    walk = MediaDownloadCollectionQuery.build().walk_statement(order=order)
    for row in session.execute(walk, execution_options={"yield_per": 1024}):
        facets[row.status] = facets.get(row.status, 0) + 1
        if wanted and row.status not in wanted:
            continue
        total += 1
        digest.update(f"{row.id},".encode("ascii"))
        for action in MEDIA_DOWNLOAD_BULK_ACTIONS:
            if supports_bulk_action(action, row.status, row.artifact_status):
                actions[action] += 1
        if len(first) <= limit:
            first.append(row)
        if passed_after and len(following) <= limit:
            following.append(row)
        if row.id == after_id:
            passed_after = True

    revision = digest.hexdigest()
    rows = first
    if after_id is not None and revision == after_revision:
        if not passed_after:
            raise LookupError(after_id)
        rows = following
    return MediaDownloadPageWindow(rows=rows, facets=facets, total=total, actions=actions, revision=revision)


def media_download_bulk_action_ids(session: Session, *, statuses: Sequence[str], action: str) -> list[int]:
    """Every download in the filtered collection that takes part in one bulk action."""
    if action not in MEDIA_DOWNLOAD_BULK_ACTIONS:
        raise ValueError(f"Unknown media download bulk action: {action}")
    wanted = set(statuses)
    walk = MediaDownloadCollectionQuery.build().walk_statement(order=None)
    return sorted(
        int(row.id)
        for row in session.execute(walk, execution_options={"yield_per": 1024})
        if (not wanted or row.status in wanted) and supports_bulk_action(action, row.status, row.artifact_status)
    )


def stored_sort_text(expression):
    """A timestamp sort key as the text SQLite actually stores and orders by.

    Server-side defaults store ``2026-10-25 15:32:50`` while bound datetimes
    become ``2026-10-25 15:32:50.000000``. Compared as datetimes, a cursor's
    own boundary row would sort after itself and repeat on the next page.
    """
    return type_coerce(expression, String)
