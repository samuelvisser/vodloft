from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@dataclass
class _Resource:
    id: int
    title: str
    slug: str


def _session() -> tuple[Session, Engine]:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_factory_creates_operation_target_and_context():
    from task_manager.scheduler.operation_factory import OperationDefinition, create_operation

    class IndexOperation(OperationDefinition[_Resource]):
        kind = "collection.index"
        resource_type = "collection"
        task = "test_worker"

        def context(self) -> dict[str, str]:
            return {"collection_slug": self.resource.slug}

    session, engine = _session()
    try:
        operation = create_operation(
            session,
            IndexOperation(_Resource(id=42, title="Test Show", slug="test-collection")),
        )

        assert operation.kind == "collection.index"
        assert operation.resource_type == "collection"
        assert operation.resource_id == 42
        assert operation.title == "Test Show"
        assert operation.context == {"collection_slug": "test-collection"}
        assert len(operation.targets) == 1
        assert operation.targets[0].task_key == "test_worker"
        assert operation.targets[0].resource_type == "collection"
        assert operation.targets[0].resource_id == 42
        assert session.info.get("vodloft.pending_events", []) == []
    finally:
        session.close()
        engine.dispose()


def test_factory_coalesces_with_compatible_running_work_without_dispatching():
    from task_manager.scheduler.db import TaskDefinition, TaskRun
    from task_manager.scheduler.operation_factory import OperationDefinition, create_operation
    from task_manager.scheduler.types import OperationStatus, ResourceType, TaskStatus

    class SyncOperation(OperationDefinition[_Resource]):
        kind = "collection.sync"
        resource_type = "collection"
        task = "test_worker"

    session, engine = _session()
    try:
        definition = TaskDefinition(
            key="test_worker",
            title="Test worker",
            description=None,
            allowed_resource_types=["collection"],
            default_max_retries=0,
        )
        session.add(definition)
        session.flush()

        run = TaskRun(
            schedule_id=None,
            definition_id=definition.id,
            resource_type=ResourceType.COLLECTION,
            resource_id=42,
            status=TaskStatus.RUNNING,
            progress=35,
            message="Working",
            meta=None,
            result=None,
            attempt_count=1,
            max_retries=0,
            last_error=None,
            next_retry_at=None,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            runtime_ms=None,
        )
        session.add(run)
        session.flush()

        operation = create_operation(
            session,
            SyncOperation(_Resource(id=42, title="Test Show", slug="test-collection")),
        )

        assert operation.status == OperationStatus.RUNNING.value
        assert operation.progress == 35
        assert session.info.get("vodloft.pending_events", []) == []
    finally:
        session.close()
        engine.dispose()
