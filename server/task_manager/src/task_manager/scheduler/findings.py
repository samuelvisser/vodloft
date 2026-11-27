"""Which runs of a task found nothing, so a task log can hide them."""
from __future__ import annotations

from sqlalchemy import and_, false, or_
from sqlalchemy.sql.elements import ColumnElement

from backend.db.json_sql import json_count
from task_manager.scheduler.db import TaskDefinition, TaskRun
from task_manager.scheduler.registry import all_definitions, task_meta
from task_manager.scheduler.types import TaskStatus


def finds_things(definition_key: str | None) -> bool:
    """Whether a log of this task, or of every task (None), can leave out the runs that found nothing."""
    if definition_key is None:
        return True
    meta = task_meta(definition_key)
    return meta is not None and bool(meta.findings)


def _found_nothing(findings: tuple[str, ...]) -> ColumnElement[bool]:
    found = sum(json_count(TaskRun.result, "data", *finding.split(".")) for finding in findings)
    return and_(TaskRun.status == TaskStatus.SUCCEEDED, found == 0)


def found_nothing(definition_key: str | None) -> ColumnElement[bool]:
    """Runs of the task, or of every task (None), that succeeded with each of their findings 0, empty or missing.

    A failed, canceled or unfinished run always counts as something to see, and so does every run of a task
    that names no findings. Without a task, the query must join TaskDefinition.
    """
    if definition_key is not None:
        meta = task_meta(definition_key)
        return _found_nothing(meta.findings) if meta is not None and meta.findings else false()
    tasks = [meta for meta in all_definitions() if meta.findings]
    return or_(false(), *(and_(TaskDefinition.key == meta.key, _found_nothing(meta.findings)) for meta in tasks))
