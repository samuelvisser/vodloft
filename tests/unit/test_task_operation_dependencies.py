from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _session() -> Session:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _operation(session: Session, resource_id: int):
    from task_manager.scheduler.operations import create_operation

    return create_operation(
        session,
        kind="test.child",
        resource_type="media_download",
        resource_id=resource_id,
        title=f"Child {resource_id}",
        targets=[],
    )


def test_parent_tracks_weighted_child_completion_without_replacing_child_progress():
    from task_manager.scheduler.operations import (
        OperationDependencySpec,
        add_operation_dependencies,
        create_operation,
        refresh_operation,
    )
    from task_manager.scheduler.types import OperationStatus

    session = _session()
    try:
        first = _operation(session, 1)
        second = _operation(session, 2)
        first.status = OperationStatus.RUNNING.value
        first.progress = 80
        first.completion_progress = 20
        second.status = OperationStatus.RUNNING.value
        second.progress = 10
        second.completion_progress = 40

        parent = create_operation(
            session,
            kind="test.composite",
            resource_type="system",
            resource_id=None,
            title="Composite",
            targets=[],
        )
        add_operation_dependencies(
            session,
            parent.id,
            (
                OperationDependencySpec(first.id, slot_key="first", weight=1),
                OperationDependencySpec(second.id, slot_key="second", weight=3),
            ),
        )

        refresh_operation(session, parent.id)
        assert parent.status == OperationStatus.RUNNING.value
        assert parent.completion_progress == 35
        assert parent.progress == 28
        assert first.progress == 80
        assert second.progress == 10

        now = datetime.now(timezone.utc)
        for child in (first, second):
            child.status = OperationStatus.SUCCEEDED.value
            child.progress = 100
            child.completion_progress = 100
            child.finished_at = now
        session.flush()
        refresh_operation(session, first.id)
        refresh_operation(session, second.id)

        assert parent.status == OperationStatus.SUCCEEDED.value
        assert parent.progress == 100
        assert parent.completion_progress == 100
    finally:
        session.close()


def test_dependency_graph_rejects_cycles_and_duplicate_children():
    from task_manager.scheduler.operations import (
        OperationDependencySpec,
        add_operation_dependencies,
    )

    session = _session()
    try:
        parent = _operation(session, 1)
        child = _operation(session, 2)
        add_operation_dependencies(
            session,
            parent.id,
            (OperationDependencySpec(child.id, slot_key="child"),),
        )

        with pytest.raises(ValueError, match="acyclic"):
            add_operation_dependencies(
                session,
                child.id,
                (OperationDependencySpec(parent.id, slot_key="parent"),),
            )

        with pytest.raises(ValueError, match="same child operation"):
            add_operation_dependencies(
                session,
                parent.id,
                (OperationDependencySpec(child.id, slot_key="other-child"),),
            )
    finally:
        session.close()
