from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from task_manager import cancel_task, prioritize_task, reload_schedules, submit_task, sync_registry_to_db
from task_manager.tasks import load_all_tasks

from backend.db import get_session
from backend.db.models import TaskDefinition, TaskOperation, TaskRun, TaskSchedule
from backend.schemas.tasks import (
    TaskDefinitionRead,
    TaskLedgerRead,
    TaskOperationRead,
    TaskRunRead,
    TaskScheduleCreate,
    TaskScheduleRead,
    TaskScheduleUpdate,
    TaskTriggerCreate,
    task_run_read,
    task_schedule_read,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _ensure_definitions() -> None:
    load_all_tasks()
    sync_registry_to_db()


def _trigger_args(payload: TaskScheduleCreate | TaskScheduleUpdate, current: TaskSchedule | None = None) -> tuple[str, dict]:
    trigger_type = payload.trigger_type or (current.trigger_type if current else "cron")
    if trigger_type == "cron":
        cron = payload.cron
        if cron is None and current and current.trigger_type == "cron":
            cron = (current.trigger_args or {}).get("cron")
        if not cron:
            raise HTTPException(status_code=422, detail="cron is required for cron schedules")
        return trigger_type, {"cron": cron}
    minutes = payload.interval_minutes
    if minutes is None and current and current.trigger_type == "interval":
        minutes = (current.trigger_args or {}).get("minutes")
    if not minutes:
        raise HTTPException(status_code=422, detail="interval_minutes is required for interval schedules")
    return trigger_type, {"minutes": int(minutes)}


@router.get("", response_model=list[TaskRunRead])
def recent_tasks(limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_session)):
    runs = list(session.scalars(select(TaskRun).order_by(TaskRun.id.desc()).limit(limit)))
    return [task_run_read(run) for run in runs]


@router.get("/definitions", response_model=list[TaskDefinitionRead])
def list_definitions(session: Session = Depends(get_session)):
    _ensure_definitions()
    session.expire_all()
    return list(session.scalars(select(TaskDefinition).order_by(TaskDefinition.title)))


@router.get("/schedules", response_model=list[TaskScheduleRead])
def list_schedules(session: Session = Depends(get_session)):
    return [task_schedule_read(item) for item in session.scalars(select(TaskSchedule).order_by(TaskSchedule.name))]


@router.post("/schedules", response_model=TaskScheduleRead, status_code=201)
def create_schedule(payload: TaskScheduleCreate, session: Session = Depends(get_session)):
    _ensure_definitions()
    definition = session.scalar(select(TaskDefinition).where(TaskDefinition.key == payload.task_key))
    if definition is None:
        raise HTTPException(status_code=404, detail="Task definition not found")
    if payload.resource_type not in definition.allowed_resource_types:
        raise HTTPException(status_code=422, detail="Resource type is not allowed for this task")
    trigger_type, trigger_args = _trigger_args(payload)
    schedule = TaskSchedule(
        definition_id=definition.id,
        name=payload.name,
        source="user",
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        trigger_type=trigger_type,
        trigger_args=trigger_args,
        payload=payload.payload,
        active=payload.active,
        coalesce=payload.coalesce,
        max_retries=payload.max_retries,
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    reload_schedules()
    return task_schedule_read(schedule)


@router.put("/schedules/{schedule_id}", response_model=TaskScheduleRead)
def update_schedule(schedule_id: int, payload: TaskScheduleUpdate, session: Session = Depends(get_session)):
    schedule = session.get(TaskSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.source == "registry":
        raise HTTPException(status_code=409, detail="Registry schedules are controlled by Python task decorators")
    changes = payload.model_dump(exclude_unset=True, exclude={"cron", "interval_minutes", "trigger_type"})
    resource_type = changes.get("resource_type", schedule.resource_type)
    if resource_type not in schedule.definition.allowed_resource_types:
        raise HTTPException(status_code=422, detail="Resource type is not allowed for this task")
    trigger_type, trigger_args = _trigger_args(payload, schedule)
    for key, value in changes.items():
        setattr(schedule, key, value)
    schedule.trigger_type = trigger_type
    schedule.trigger_args = trigger_args
    session.commit()
    session.refresh(schedule)
    reload_schedules()
    return task_schedule_read(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, session: Session = Depends(get_session)):
    schedule = session.get(TaskSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.source == "registry":
        raise HTTPException(status_code=409, detail="Registry schedules are controlled by Python task decorators")
    session.delete(schedule)
    session.commit()
    reload_schedules()
    return Response(status_code=204)


@router.post("/trigger", response_model=TaskRunRead, status_code=202)
def trigger_task(payload: TaskTriggerCreate):
    try:
        run = submit_task(
            payload.task_key,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            payload=payload.payload,
            max_retries=payload.max_retries,
            source="api",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return task_run_read(run)


@router.get("/runs", response_model=list[TaskRunRead])
def list_runs(
    status: str | None = None,
    task_key: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    statement = select(TaskRun).join(TaskDefinition)
    if status:
        statement = statement.where(TaskRun.status == status)
    if task_key:
        statement = statement.where(TaskDefinition.key == task_key)
    if resource_type:
        statement = statement.where(TaskRun.resource_type == resource_type)
    if resource_id is not None:
        statement = statement.where(TaskRun.resource_id == resource_id)
    runs = list(session.scalars(statement.order_by(TaskRun.id.desc()).limit(limit)))
    return [task_run_read(run) for run in runs]


@router.get("/ledger", response_model=TaskLedgerRead)
def task_ledger(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    task_key: str | None = None,
    resource_type: str | None = None,
    session: Session = Depends(get_session),
):
    filters = []
    if status:
        filters.append(TaskRun.status == status)
    if resource_type:
        filters.append(TaskRun.resource_type == resource_type)
    base = select(TaskRun).join(TaskDefinition)
    count = select(func.count(TaskRun.id)).select_from(TaskRun).join(TaskDefinition)
    if task_key:
        filters.append(TaskDefinition.key == task_key)
    if filters:
        base = base.where(*filters)
        count = count.where(*filters)
    total = int(session.scalar(count) or 0)
    runs = list(
        session.scalars(
            base.order_by(TaskRun.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return TaskLedgerRead(
        items=[task_run_read(run) for run in runs],
        page=page,
        page_size=page_size,
        total=total,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/operations", response_model=list[TaskOperationRead])
def list_operations(limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_session)):
    return list(session.scalars(select(TaskOperation).order_by(TaskOperation.id.desc()).limit(limit)))


@router.get("/operations/{operation_id}", response_model=TaskOperationRead)
def get_operation(operation_id: int, session: Session = Depends(get_session)):
    operation = session.get(TaskOperation, operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Task operation not found")
    return operation


@router.get("/{run_id}", response_model=TaskRunRead)
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(TaskRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Task run not found")
    return task_run_read(run)


@router.post("/{run_id}/prioritize", status_code=202)
def prioritize_run(run_id: int):
    if not prioritize_task(run_id):
        raise HTTPException(status_code=409, detail="Only queued task runs can be prioritized")
    return {"status": "prioritized", "run_id": run_id}


@router.post("/{run_id}/cancel", status_code=202)
def cancel_run(run_id: int):
    if not cancel_task(run_id):
        raise HTTPException(status_code=409, detail="Task cannot be canceled")
    return {"status": "cancellation_requested", "run_id": run_id}
