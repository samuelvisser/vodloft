"""Which runs of a task found nothing, so a task log can hide them."""
from __future__ import annotations

from sqlalchemy import and_, literal
from sqlalchemy.sql.elements import ColumnElement

from backend.db.json_sql import json_count
from task_manager.scheduler.db import TaskRun
from task_manager.scheduler.registry import task_meta
from task_manager.scheduler.types import TaskStatus


def finds_things(definition_key: str) -> bool:
    """Whether the task names what its runs find, so its log can leave out the runs that found nothing."""
    meta = task_meta(definition_key)
    return meta is not None and bool(meta.findings)


def found_nothing(definition_key: str) -> ColumnElement[bool]:
    """Runs of the task that succeeded with each of its findings 0, empty or missing.

    A failed, canceled or unfinished run always counts as something to see.
    """
    meta = task_meta(definition_key)
    if meta is None or not meta.findings:
        return literal(False)
    found = sum(
        (json_count(TaskRun.result, "data", *finding.split(".")) for finding in meta.findings),
        start=literal(0),
    )
    return and_(TaskRun.status == TaskStatus.SUCCEEDED, found == 0)
