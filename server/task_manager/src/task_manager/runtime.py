from __future__ import annotations

import json
import logging
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event as ThreadEvent, RLock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from config import get_settings
from sqlalchemy import func, select

from backend.db import SessionLocal
from backend.db.models import TaskDefinition, TaskOperation, TaskRun, TaskSchedule

from .events import EVENT_BUS, Event
from .registry import all_definitions, all_tasks, all_triggers, get_task
from .types import OperationSource, OperationStatus, TaskCancelled, TaskResult, TaskStatus

logger = logging.getLogger(__name__)
ACTIVE_STATUSES = {
    TaskStatus.SCHEDULED.value,
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
    TaskStatus.RETRY_SCHEDULED.value,
}
TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELED.value,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


class TaskContext:
    def __init__(self, run_id: int, runtime: "TaskRuntime") -> None:
        self.run_id = run_id
        self._runtime = runtime

    def report(self, progress: int, message: str | None = None) -> None:
        self.check_cancelled()
        self._runtime.report(self.run_id, progress, message)

    def check_cancelled(self) -> None:
        if self._runtime.cancellation_requested(self.run_id):
            raise TaskCancelled("Task cancellation requested")

    def emit(
        self,
        event_name: str,
        *,
        resource_type: str,
        resource_id: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        emit_event(
            event_name,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
        )

    def submit(
        self,
        task_key: str,
        *,
        resource_type: str,
        resource_id: int,
        payload: dict[str, Any] | None = None,
        operation_id: int | None = None,
        dedupe_key: str | None = None,
        source: str = OperationSource.SYSTEM.value,
    ) -> TaskRun:
        return submit_task(
            task_key,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
            operation_id=operation_id,
            dedupe_key=dedupe_key,
            source=source,
        )

    def create_operation(
        self,
        title: str,
        *,
        source: str = OperationSource.SYSTEM.value,
        meta: dict[str, Any] | None = None,
    ) -> TaskOperation:
        return create_operation(title, source=source, meta=meta)


class TaskRuntime:
    def __init__(self) -> None:
        settings = get_settings()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.worker_threads,
            thread_name_prefix="vodloft-task",
        )
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._lock = RLock()
        self._futures: dict[int, Future[Any]] = {}
        self._cancel_flags: dict[int, ThreadEvent] = {}
        self._active_task_slots: dict[str, int] = {}
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            from .tasks import load_all_tasks

            load_all_tasks()
            sync_registry_to_db()
            self._sync_registry_schedules()
            self._configure_event_triggers()
            self._scheduler.start()
            self._register_database_schedules()
            recovered = self._recover_interrupted_runs()
            self._started = True
            for run_id in recovered:
                self._submit_existing(run_id)
            emit_event("app.startup", resource_type="system", resource_id=0)

    def shutdown(self) -> None:
        with self._lock:
            if not self._started:
                return
            emit_event("app.shutdown", resource_type="system", resource_id=0)
            EVENT_BUS.clear()
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._started = False

    def _configure_event_triggers(self) -> None:
        EVENT_BUS.clear()
        for task_key, triggers in all_triggers().items():
            for trigger in triggers:
                if trigger.trigger_type != "event" or not trigger.event_name:
                    continue

                def listener(event: Event, *, key: str = task_key, expected: str | None = trigger.resource_type) -> None:
                    if expected is not None and event.resource_type != expected:
                        return
                    try:
                        submit_task(
                            key,
                            resource_type=event.resource_type,
                            resource_id=event.resource_id,
                            payload=event.payload,
                            source=OperationSource.EVENT.value,
                        )
                    except Exception:
                        logger.exception("Event-triggered task %s could not be submitted", key)

                EVENT_BUS.subscribe(trigger.event_name, listener)

    def _sync_registry_schedules(self) -> None:
        with SessionLocal() as session:
            definitions = {item.key: item for item in session.scalars(select(TaskDefinition))}
            wanted: set[str] = set()
            for task_key, triggers in all_triggers().items():
                definition = definitions.get(task_key)
                if definition is None:
                    continue
                schedule_index = 0
                for trigger in triggers:
                    if trigger.trigger_type not in {"cron", "interval"}:
                        continue
                    registry_key = f"{task_key}:{trigger.trigger_type}:{schedule_index}"
                    schedule_index += 1
                    wanted.add(registry_key)
                    schedule = session.scalar(
                        select(TaskSchedule).where(TaskSchedule.registry_key == registry_key)
                    )
                    if schedule is None:
                        schedule = TaskSchedule(
                            definition_id=definition.id,
                            name=f"{definition.title} ({trigger.trigger_type})",
                            source="registry",
                            registry_key=registry_key,
                            resource_type=trigger.resource_type or "system",
                            resource_id=trigger.resource_id or 0,
                            active=True,
                            coalesce=trigger.coalesce,
                        )
                        session.add(schedule)
                    schedule.definition_id = definition.id
                    schedule.trigger_type = trigger.trigger_type
                    schedule.trigger_args = (
                        {"cron": trigger.cron}
                        if trigger.trigger_type == "cron"
                        else {"minutes": trigger.interval_minutes}
                    )
                    schedule.active = True
                    schedule.coalesce = trigger.coalesce
            for schedule in session.scalars(select(TaskSchedule).where(TaskSchedule.source == "registry")):
                if schedule.registry_key not in wanted:
                    schedule.active = False
            session.commit()

    def _make_trigger(self, schedule: TaskSchedule):
        args = schedule.trigger_args or {}
        if schedule.trigger_type == "cron":
            cron = str(args.get("cron") or "")
            if not cron:
                raise ValueError("Cron schedule is missing a cron expression")
            return CronTrigger.from_crontab(cron, timezone="UTC")
        if schedule.trigger_type == "interval":
            minutes = int(args.get("minutes") or 0)
            if minutes < 1:
                raise ValueError("Interval schedule must be at least one minute")
            return IntervalTrigger(minutes=minutes, timezone="UTC")
        raise ValueError(f"Unsupported trigger type: {schedule.trigger_type}")

    def _register_database_schedules(self) -> None:
        if not self._scheduler.running:
            return
        if not get_settings().scheduler.enabled:
            return
        for job in list(self._scheduler.get_jobs()):
            if job.id.startswith("schedule:"):
                self._scheduler.remove_job(job.id)
        with SessionLocal() as session:
            schedules = list(session.scalars(select(TaskSchedule).where(TaskSchedule.active.is_(True))))
            for schedule in schedules:
                try:
                    trigger = self._make_trigger(schedule)
                except Exception as exc:
                    schedule.last_error = str(exc)
                    continue
                self._scheduler.add_job(
                    self._fire_schedule,
                    trigger=trigger,
                    id=f"schedule:{schedule.id}",
                    args=[schedule.id],
                    replace_existing=True,
                    coalesce=schedule.coalesce,
                    max_instances=1,
                    misfire_grace_time=300,
                )
                schedule.last_error = None
            session.commit()
        self.refresh_next_run_times()

    def reload_schedules(self) -> None:
        with self._lock:
            self._register_database_schedules()

    def refresh_next_run_times(self) -> None:
        if not self._scheduler.running:
            return
        with SessionLocal() as session:
            changed = False
            for schedule in session.scalars(select(TaskSchedule)):
                job = self._scheduler.get_job(f"schedule:{schedule.id}")
                next_run = job.next_run_time if job is not None else None
                if schedule.next_run_time != next_run:
                    schedule.next_run_time = next_run
                    changed = True
            if changed:
                session.commit()

    def _fire_schedule(self, schedule_id: int) -> None:
        with SessionLocal() as session:
            schedule = session.get(TaskSchedule, schedule_id)
            if schedule is None or not schedule.active:
                return
            definition = session.get(TaskDefinition, schedule.definition_id)
            if definition is None:
                return
            task_key = definition.key
            resource_type = schedule.resource_type
            resource_id = schedule.resource_id
            payload = dict(schedule.payload or {})
            max_retries = schedule.max_retries
        try:
            submit_task(
                task_key,
                resource_type=resource_type,
                resource_id=resource_id,
                payload=payload,
                max_retries=max_retries,
                schedule_id=schedule_id,
                source=OperationSource.SCHEDULE.value,
            )
        except Exception:
            logger.exception("Scheduled task %s failed to queue", task_key)
        finally:
            self.refresh_next_run_times()

    def _recover_interrupted_runs(self) -> list[int]:
        now = utcnow()
        queued: list[int] = []
        with SessionLocal() as session:
            runs = list(session.scalars(select(TaskRun).where(TaskRun.status.in_(ACTIVE_STATUSES))))
            for run in runs:
                retry_at = _as_utc(run.next_retry_at)
                if run.status == TaskStatus.RETRY_SCHEDULED.value and retry_at and retry_at > now:
                    self._schedule_retry(run.id, retry_at)
                    continue
                run.status = TaskStatus.QUEUED.value
                run.message = "Recovered after application restart"
                run.next_retry_at = None
                run.cancellation_requested = False
                run.updated_at = now
                queued.append(run.id)
            session.commit()
        return queued

    def submit(
        self,
        task_key: str,
        *,
        resource_type: str,
        resource_id: int,
        payload: dict[str, Any] | None = None,
        max_retries: int | None = None,
        schedule_id: int | None = None,
        operation_id: int | None = None,
        dedupe_key: str | None = None,
        source: str = OperationSource.API.value,
    ) -> TaskRun:
        try:
            meta, _ = get_task(task_key)
        except KeyError as exc:
            raise LookupError(f"Unknown task definition: {task_key}") from exc
        if resource_type not in meta.allowed_resource_types:
            raise ValueError(f"Task {task_key} does not allow resource type {resource_type}")

        with self._lock, SessionLocal() as session:
            definition = session.scalar(select(TaskDefinition).where(TaskDefinition.key == task_key))
            if definition is None:
                sync_registry_to_db()
                definition = session.scalar(select(TaskDefinition).where(TaskDefinition.key == task_key))
            if definition is None:
                raise RuntimeError(f"Task definition {task_key} was not synchronized")

            effective_dedupe = dedupe_key or f"{task_key}:{resource_type}:{resource_id}"
            existing = session.scalar(
                select(TaskRun)
                .where(TaskRun.dedupe_key == effective_dedupe, TaskRun.status.in_(ACTIVE_STATUSES))
                .order_by(TaskRun.id.desc())
            )
            if existing is not None:
                return existing

            retries = max_retries
            if retries is None:
                retries = definition.default_max_retries
            if retries is None:
                retries = get_settings().task_manager.default_max_retries

            now = utcnow()
            run = TaskRun(
                definition_id=definition.id,
                schedule_id=schedule_id,
                operation_id=operation_id,
                resource_type=resource_type,
                resource_id=resource_id,
                source=source,
                status=TaskStatus.QUEUED.value,
                progress=0,
                message="Queued",
                payload=_jsonable(payload or {}),
                max_retries=max(0, int(retries)),
                dedupe_key=effective_dedupe,
                queued_at=now,
                progress_updated_at=now,
            )
            session.add(run)
            if operation_id is not None:
                operation = session.get(TaskOperation, operation_id)
                if operation is not None:
                    operation.total_tasks += 1
                    if operation.status in {
                        OperationStatus.SUCCEEDED.value,
                        OperationStatus.FAILED.value,
                        OperationStatus.CANCELED.value,
                        OperationStatus.PARTIAL.value,
                    }:
                        operation.status = OperationStatus.RUNNING.value
                        operation.finished_at = None
            session.commit()
            session.refresh(run)
            self._cancel_flags[run.id] = ThreadEvent()
            self._submit_existing(run.id)
            return run

    def _submit_existing(self, run_id: int) -> bool:
        with self._lock:
            if run_id in self._futures and not self._futures[run_id].done():
                return False
            with SessionLocal() as session:
                run = session.get(TaskRun, run_id)
                if run is None or run.status != TaskStatus.QUEUED.value:
                    return False
                definition = session.get(TaskDefinition, run.definition_id)
                if definition is None:
                    return False
                task_key = definition.key
            try:
                meta, _ = get_task(task_key)
            except KeyError:
                return False
            if meta.max_concurrency is not None:
                active = self._active_task_slots.get(task_key, 0)
                if active >= meta.max_concurrency:
                    return False
                self._active_task_slots[task_key] = active + 1
            self._cancel_flags.setdefault(run_id, ThreadEvent())
            self._futures[run_id] = self._executor.submit(self._execute_with_slot, run_id, task_key)
            return True

    def _execute_with_slot(self, run_id: int, task_key: str) -> None:
        try:
            self._execute(run_id)
        finally:
            try:
                meta, _ = get_task(task_key)
            except KeyError:
                meta = None
            if meta is not None and meta.max_concurrency is not None:
                with self._lock:
                    self._active_task_slots[task_key] = max(0, self._active_task_slots.get(task_key, 1) - 1)
                self._dispatch_queued(task_key)

    def _dispatch_queued(self, task_key: str) -> None:
        try:
            meta, _ = get_task(task_key)
        except KeyError:
            return
        if meta.max_concurrency is None:
            return
        while True:
            with self._lock:
                if self._active_task_slots.get(task_key, 0) >= meta.max_concurrency:
                    return
                with SessionLocal() as session:
                    definition = session.scalar(select(TaskDefinition).where(TaskDefinition.key == task_key))
                    if definition is None:
                        return
                    run_id = session.scalar(
                        select(TaskRun.id)
                        .where(
                            TaskRun.definition_id == definition.id,
                            TaskRun.status == TaskStatus.QUEUED.value,
                            TaskRun.cancellation_requested.is_(False),
                        )
                        .order_by(
                            TaskRun.priority_at.is_(None),
                            TaskRun.priority_at.desc(),
                            TaskRun.queued_at.asc(),
                            TaskRun.id.asc(),
                        )
                        .limit(1)
                    )
                if run_id is None:
                    return
                if not self._submit_existing(run_id):
                    return

    def _execute(self, run_id: int) -> None:
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.status not in ACTIVE_STATUSES:
                return
            definition = session.get(TaskDefinition, run.definition_id)
            if definition is None:
                self._finalize(run_id, TaskStatus.FAILED, "Task definition is missing")
                return
            if run.cancellation_requested:
                self._finalize(run_id, TaskStatus.CANCELED, "Canceled")
                return
            task_key = definition.key
            run.status = TaskStatus.RUNNING.value
            run.started_at = run.started_at or utcnow()
            run.updated_at = utcnow()
            run.attempt_count += 1
            run.message = "Running"
            operation_id = run.operation_id
            resource_type = run.resource_type
            resource_id = run.resource_id
            payload = dict(run.payload or {})
            session.commit()
            if operation_id is not None:
                operation = session.get(TaskOperation, operation_id)
                if operation is not None and operation.status == OperationStatus.QUEUED.value:
                    operation.status = OperationStatus.RUNNING.value
                    operation.started_at = operation.started_at or utcnow()
                    session.commit()

        context = TaskContext(run_id, self)
        try:
            context.check_cancelled()
            _meta, worker = get_task(task_key)
            value = worker(context, resource_type, resource_id, payload)
            context.check_cancelled()
            if isinstance(value, TaskResult):
                result = value.result
                message = value.message or "Completed"
            else:
                result = value
                message = "Completed"
        except TaskCancelled:
            self._finalize(run_id, TaskStatus.CANCELED, "Canceled")
            return
        except Exception as exc:
            logger.error("Task %s run %s failed: %s\n%s", task_key, run_id, exc, traceback.format_exc())
            if self._retry_or_fail(run_id, exc):
                return
            self._finalize(run_id, TaskStatus.FAILED, "Failed", error=str(exc))
            return
        self._finalize(run_id, TaskStatus.SUCCEEDED, message, result=result)

    def _retry_or_fail(self, run_id: int, exc: Exception) -> bool:
        settings = get_settings().task_manager
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.cancellation_requested:
                return False
            if run.attempt_count > run.max_retries:
                return False
            delay = min(
                settings.retry_backoff_max_seconds,
                settings.retry_backoff_base_seconds * (2 ** max(0, run.attempt_count - 1)),
            )
            when = utcnow() + timedelta(seconds=delay)
            run.status = TaskStatus.RETRY_SCHEDULED.value
            run.last_error = str(exc)
            run.message = f"Retrying in {delay} seconds"
            run.next_retry_at = when
            run.updated_at = utcnow()
            session.commit()
        self._schedule_retry(run_id, when)
        return True

    def _schedule_retry(self, run_id: int, when: datetime) -> None:
        if not self._scheduler.running:
            return
        self._scheduler.add_job(
            self._resume_run,
            trigger=DateTrigger(run_date=when, timezone="UTC"),
            id=f"retry:{run_id}",
            args=[run_id],
            replace_existing=True,
            misfire_grace_time=300,
        )

    def _resume_run(self, run_id: int) -> None:
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.status != TaskStatus.RETRY_SCHEDULED.value:
                return
            if run.cancellation_requested:
                run.status = TaskStatus.CANCELED.value
                run.finished_at = utcnow()
                run.message = "Canceled"
                session.commit()
                self._update_operation(run.operation_id)
                return
            run.status = TaskStatus.QUEUED.value
            run.next_retry_at = None
            run.message = "Queued for retry"
            run.queued_at = utcnow()
            session.commit()
        self._submit_existing(run_id)

    def report(self, run_id: int, progress: int, message: str | None = None) -> None:
        progress = max(0, min(100, int(progress)))
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.status != TaskStatus.RUNNING.value:
                return
            changed = run.progress != progress
            if changed:
                run.progress = progress
                run.progress_updated_at = utcnow()
            if message is not None:
                run.message = message
            if changed or message is not None:
                run.updated_at = utcnow()
                session.commit()

    def cancellation_requested(self, run_id: int) -> bool:
        flag = self._cancel_flags.get(run_id)
        if flag is not None and flag.is_set():
            return True
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            requested = bool(run and run.cancellation_requested)
        if requested:
            self._cancel_flags.setdefault(run_id, ThreadEvent()).set()
        return requested

    def cancel(self, run_id: int) -> bool:
        with self._lock, SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.status in TERMINAL_STATUSES:
                return False
            run.cancellation_requested = True
            run.message = "Cancellation requested"
            run.updated_at = utcnow()
            session.commit()
            self._cancel_flags.setdefault(run_id, ThreadEvent()).set()
            future = self._futures.get(run_id)
            task_key = run.definition.key if run.definition is not None else None
            if run.status in {TaskStatus.SCHEDULED.value, TaskStatus.RETRY_SCHEDULED.value}:
                retry_job = self._scheduler.get_job(f"retry:{run_id}") if self._scheduler.running else None
                if retry_job is not None:
                    self._scheduler.remove_job(retry_job.id)
                self._finalize(run_id, TaskStatus.CANCELED, "Canceled")
            elif run.status == TaskStatus.QUEUED.value and future is None:
                self._finalize(run_id, TaskStatus.CANCELED, "Canceled")
            elif run.status == TaskStatus.QUEUED.value and future is not None and future.cancel():
                if task_key is not None:
                    try:
                        meta, _ = get_task(task_key)
                    except KeyError:
                        meta = None
                    if meta is not None and meta.max_concurrency is not None:
                        self._active_task_slots[task_key] = max(0, self._active_task_slots.get(task_key, 1) - 1)
                self._finalize(run_id, TaskStatus.CANCELED, "Canceled")
                if task_key is not None:
                    self._dispatch_queued(task_key)
            return True

    def prioritize(self, run_id: int) -> bool:
        task_key: str | None = None
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None or run.status != TaskStatus.QUEUED.value:
                return False
            definition = session.get(TaskDefinition, run.definition_id)
            if definition is None:
                return False
            run.priority_at = utcnow()
            run.message = "Prioritized in queue"
            run.updated_at = utcnow()
            task_key = definition.key
            session.commit()
        if task_key is not None:
            self._dispatch_queued(task_key)
        return True

    def _finalize(
        self,
        run_id: int,
        status: TaskStatus,
        message: str,
        *,
        error: str | None = None,
        result: Any = None,
    ) -> None:
        operation_id: int | None = None
        task_key: str | None = None
        now = utcnow()
        with SessionLocal() as session:
            run = session.get(TaskRun, run_id)
            if run is None:
                return
            if run.status in TERMINAL_STATUSES and run.finished_at is not None:
                return
            definition = session.get(TaskDefinition, run.definition_id)
            task_key = definition.key if definition else None
            run.status = status.value
            run.message = message
            run.last_error = error or run.last_error
            run.result = _jsonable(result)
            run.finished_at = now
            run.next_retry_at = None
            run.updated_at = now
            if status == TaskStatus.SUCCEEDED:
                run.progress = 100
                run.progress_updated_at = now
                run.last_error = None
            started_at = _as_utc(run.started_at)
            if started_at is not None:
                run.runtime_seconds = max(0.0, (now - started_at).total_seconds())
            operation_id = run.operation_id
            session.commit()
        self._update_operation(operation_id)
        if task_key is not None:
            try:
                meta, _ = get_task(task_key)
                if meta.terminal_callback is not None:
                    meta.terminal_callback(run_id, status.value)
            except Exception:
                logger.exception("Terminal callback failed for task run %s", run_id)
        emit_event(
            f"task.{status.value}",
            resource_type="task_run",
            resource_id=run_id,
            payload={"task_key": task_key or "", "status": status.value},
        )

    def _update_operation(self, operation_id: int | None) -> None:
        if operation_id is None:
            return
        with SessionLocal() as session:
            operation = session.get(TaskOperation, operation_id)
            if operation is None:
                return
            counts = dict(
                session.execute(
                    select(TaskRun.status, func.count(TaskRun.id))
                    .where(TaskRun.operation_id == operation_id)
                    .group_by(TaskRun.status)
                ).all()
            )
            succeeded = int(counts.get(TaskStatus.SUCCEEDED.value, 0))
            failed = int(counts.get(TaskStatus.FAILED.value, 0))
            canceled = int(counts.get(TaskStatus.CANCELED.value, 0))
            completed = succeeded + failed + canceled
            operation.succeeded_tasks = succeeded
            operation.failed_tasks = failed
            operation.canceled_tasks = canceled
            operation.completed_tasks = completed
            if completed < operation.total_tasks:
                operation.status = OperationStatus.RUNNING.value
                operation.started_at = operation.started_at or utcnow()
                operation.finished_at = None
            elif operation.total_tasks == 0:
                operation.status = OperationStatus.QUEUED.value
            else:
                if failed and succeeded:
                    operation.status = OperationStatus.PARTIAL.value
                elif failed:
                    operation.status = OperationStatus.FAILED.value
                elif canceled and succeeded:
                    operation.status = OperationStatus.PARTIAL.value
                elif canceled:
                    operation.status = OperationStatus.CANCELED.value
                else:
                    operation.status = OperationStatus.SUCCEEDED.value
                operation.finished_at = utcnow()
            session.commit()

    def mark_stalled_runs(self) -> int:
        cutoff = utcnow() - timedelta(minutes=get_settings().task_manager.stalled_timeout_minutes)
        stalled_ids: list[int] = []
        with SessionLocal() as session:
            runs = list(
                session.scalars(
                    select(TaskRun)
                    .join(TaskDefinition, TaskRun.definition_id == TaskDefinition.id)
                    .where(
                        TaskRun.status == TaskStatus.RUNNING.value,
                        TaskDefinition.tracks_progress.is_(True),
                        TaskRun.progress_updated_at.is_not(None),
                        TaskRun.progress_updated_at < cutoff,
                    )
                )
            )
            for run in runs:
                run.cancellation_requested = True
                run.updated_at = utcnow()
                stalled_ids.append(run.id)
            session.commit()
        for run_id in stalled_ids:
            self._cancel_flags.setdefault(run_id, ThreadEvent()).set()
            self._finalize(
                run_id,
                TaskStatus.FAILED,
                "Task stalled with no progress",
                error="Task exceeded the stalled-progress timeout",
            )
        return len(stalled_ids)


_RUNTIME: TaskRuntime | None = None
_RUNTIME_LOCK = RLock()


def get_runtime() -> TaskRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = TaskRuntime()
        return _RUNTIME


def start_task_system() -> TaskRuntime:
    runtime = get_runtime()
    runtime.start()
    return runtime


def stop_task_system() -> None:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is not None:
            _RUNTIME.shutdown()
            _RUNTIME = None


def sync_registry_to_db() -> None:
    definitions = all_definitions()
    with SessionLocal() as session:
        existing = {item.key: item for item in session.scalars(select(TaskDefinition))}
        for meta in definitions:
            definition = existing.get(meta.key)
            if definition is None:
                definition = TaskDefinition(key=meta.key, title=meta.title)
                session.add(definition)
            definition.title = meta.title
            definition.description = meta.description
            definition.allowed_resource_types = list(meta.allowed_resource_types)
            definition.default_max_retries = meta.default_max_retries
            definition.tracks_progress = meta.tracks_progress
        session.commit()


def submit_task(
    task_key: str,
    *,
    resource_type: str,
    resource_id: int,
    payload: dict[str, Any] | None = None,
    max_retries: int | None = None,
    schedule_id: int | None = None,
    operation_id: int | None = None,
    dedupe_key: str | None = None,
    source: str = OperationSource.API.value,
) -> TaskRun:
    runtime = get_runtime()
    if not runtime.started:
        runtime.start()
    return runtime.submit(
        task_key,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        max_retries=max_retries,
        schedule_id=schedule_id,
        operation_id=operation_id,
        dedupe_key=dedupe_key,
        source=source,
    )


def cancel_task(run_id: int) -> bool:
    return get_runtime().cancel(run_id)


def prioritize_task(run_id: int) -> bool:
    return get_runtime().prioritize(run_id)


def emit_event(
    event_name: str,
    *,
    resource_type: str,
    resource_id: int,
    payload: dict[str, Any] | None = None,
) -> None:
    EVENT_BUS.emit(Event(event_name, resource_type, resource_id, payload or {}))


def create_operation(
    title: str,
    *,
    source: str = OperationSource.API.value,
    meta: dict[str, Any] | None = None,
) -> TaskOperation:
    with SessionLocal() as session:
        operation = TaskOperation(
            title=title,
            source=source,
            status=OperationStatus.QUEUED.value,
            meta=_jsonable(meta or {}),
        )
        session.add(operation)
        session.commit()
        session.refresh(operation)
        return operation


def reload_schedules() -> None:
    runtime = get_runtime()
    if runtime.started:
        runtime.reload_schedules()
