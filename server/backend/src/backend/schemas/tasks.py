from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    title: str
    description: str
    allowed_resource_types: list[str]
    default_max_retries: int | None
    tracks_progress: bool


class TaskRunRead(BaseModel):
    id: int
    task_key: str
    task_title: str
    schedule_id: int | None
    operation_id: int | None
    resource_type: str
    resource_id: int
    source: str
    status: str
    progress: int
    message: str | None
    payload: dict[str, Any]
    result: Any = None
    attempt_count: int
    max_retries: int
    last_error: str | None
    next_retry_at: datetime | None
    cancellation_requested: bool
    priority_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress_updated_at: datetime | None
    runtime_seconds: float | None
    created_at: datetime
    updated_at: datetime


class TaskLedgerRead(BaseModel):
    items: list[TaskRunRead]
    page: int
    page_size: int
    total: int
    pages: int


class TaskScheduleCreate(BaseModel):
    task_key: str
    name: str
    resource_type: str = "system"
    resource_id: int = 0
    trigger_type: Literal["cron", "interval"] = "cron"
    cron: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    payload: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    coalesce: bool = True
    max_retries: int | None = Field(default=None, ge=0, le=20)

    @model_validator(mode="after")
    def validate_trigger(self):
        if self.trigger_type == "cron" and not self.cron:
            raise ValueError("cron is required for cron schedules")
        if self.trigger_type == "interval" and self.interval_minutes is None:
            raise ValueError("interval_minutes is required for interval schedules")
        return self


class TaskScheduleUpdate(BaseModel):
    name: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    trigger_type: Literal["cron", "interval"] | None = None
    cron: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    payload: dict[str, Any] | None = None
    active: bool | None = None
    coalesce: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=20)

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        required = {"name", "resource_type", "resource_id", "trigger_type", "payload", "active", "coalesce"}
        for field in self.model_fields_set & required:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TaskScheduleRead(BaseModel):
    id: int
    task_key: str
    task_title: str
    name: str
    source: str
    registry_key: str | None
    resource_type: str
    resource_id: int
    trigger_type: str
    trigger_args: dict[str, Any]
    payload: dict[str, Any]
    active: bool
    coalesce: bool
    max_retries: int | None
    next_run_time: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TaskTriggerCreate(BaseModel):
    task_key: str
    resource_type: str
    resource_id: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    max_retries: int | None = Field(default=None, ge=0, le=20)


class TaskOperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    source: str
    status: str
    total_tasks: int
    completed_tasks: int
    succeeded_tasks: int
    failed_tasks: int
    canceled_tasks: int
    meta: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


def task_run_read(run) -> TaskRunRead:
    return TaskRunRead(
        id=run.id,
        task_key=run.definition.key,
        task_title=run.definition.title,
        schedule_id=run.schedule_id,
        operation_id=run.operation_id,
        resource_type=run.resource_type,
        resource_id=run.resource_id,
        source=run.source,
        status=run.status,
        progress=run.progress,
        message=run.message,
        payload=dict(run.payload or {}),
        result=run.result,
        attempt_count=run.attempt_count,
        max_retries=run.max_retries,
        last_error=run.last_error,
        next_retry_at=run.next_retry_at,
        cancellation_requested=run.cancellation_requested,
        priority_at=run.priority_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        progress_updated_at=run.progress_updated_at,
        runtime_seconds=run.runtime_seconds,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def task_schedule_read(schedule) -> TaskScheduleRead:
    return TaskScheduleRead(
        id=schedule.id,
        task_key=schedule.definition.key,
        task_title=schedule.definition.title,
        name=schedule.name,
        source=schedule.source,
        registry_key=schedule.registry_key,
        resource_type=schedule.resource_type,
        resource_id=schedule.resource_id,
        trigger_type=schedule.trigger_type,
        trigger_args=dict(schedule.trigger_args or {}),
        payload=dict(schedule.payload or {}),
        active=schedule.active,
        coalesce=schedule.coalesce,
        max_retries=schedule.max_retries,
        next_run_time=schedule.next_run_time,
        last_error=schedule.last_error,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )

# Backwards-compatible schema name used by the original foundation routes.
TaskRead = TaskRunRead
