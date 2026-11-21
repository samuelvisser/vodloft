from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy.orm import Session

from task_manager.scheduler.db import TaskOperation
from task_manager.scheduler.operation_control import OPERATION_CANCELABLE_CONTEXT_KEY
from task_manager.scheduler.operations import (
    OperationDependencySpec,
    OperationTargetSpec,
    create_operation as create_task_operation,
)
from sources.pacing import RequestPriority
from task_manager.scheduler.types import OperationSource


ResourceT = TypeVar("ResourceT")
REQUEST_PRIORITY_CONTEXT_KEY = "request_priority"
WORK_WEIGHT_CONTEXT_KEY = "work_weight"


def work_weight(operation: TaskOperation) -> float:
    """How much work the operation is against the other parts of an action made of several, as its definition said:
    an action counts its parts by these weights, also while a part cannot say how far it is itself."""
    value = (operation.context or {}).get(WORK_WEIGHT_CONTEXT_KEY)
    return float(value) if isinstance(value, (int, float)) and value > 0 else 1.0


class OperationDefinition(Generic[ResourceT]):
    """Declarative description of one reusable high-level operation shape."""

    kind: ClassVar[str]
    resource_type: ClassVar[str]
    task: ClassVar[str | None] = None
    request_priority: ClassVar[RequestPriority | None] = None
    cancelable: ClassVar[bool] = True
    """Whether a person may cancel the operation. Work that stopping halfway would leave half done says False, and
    then no part of VODLoft offers to cancel it."""
    """How the operation's requests to a Source queue behind others. "bulk"
    work, which touches many items at once, goes before background checks."""

    def __init__(
        self,
        resource: ResourceT,
        *,
        source: str = OperationSource.UI.value,
        work_weight: float | None = None,
    ) -> None:
        self.resource = resource
        self.source = source
        self.work_weight = work_weight
        """How much work the operation is, in the units of ``backend.types.work_weights``, when it is known in
        advance; an action made of several parts counts this one by it."""

    @property
    def resource_id(self) -> int | None:
        return getattr(self.resource, "id", None)

    @property
    def title(self) -> str:
        title = getattr(self.resource, "title", None)
        if title:
            return str(title)
        if self.resource_id is not None:
            return f"{self.resource_type} {self.resource_id}"
        return self.kind

    def task_kwargs(self) -> dict[str, Any]:
        return {}

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        if self.task is None:
            return ()
        return (
            OperationTargetSpec(
                task_key=self.task,
                resource_type=self.resource_type,
                resource_id=self.resource_id,
                task_kwargs=self.task_kwargs(),
            ),
        )

    def dependencies(self) -> tuple[OperationDependencySpec, ...]:
        return ()

    def context(self) -> dict[str, Any]:
        return {}

    def full_context(self) -> dict[str, Any]:
        """``context`` plus what every operation records about itself."""
        context = self.context()
        if self.request_priority is not None:
            context = {**context, REQUEST_PRIORITY_CONTEXT_KEY: self.request_priority}
        if self.work_weight is not None:
            context = {**context, WORK_WEIGHT_CONTEXT_KEY: self.work_weight}
        if not self.cancelable:
            context = {**context, OPERATION_CANCELABLE_CONTEXT_KEY: False}
        return context


class OperationFactory:
    """Materialize an OperationDefinition into scheduler state."""

    @staticmethod
    def create(
        session: Session,
        definition: OperationDefinition[Any],
    ) -> TaskOperation:
        return create_task_operation(
            session,
            kind=definition.kind,
            source=definition.source,
            resource_type=definition.resource_type,
            resource_id=definition.resource_id,
            title=definition.title,
            targets=tuple(definition.targets()),
            dependencies=tuple(definition.dependencies()),
            context=definition.full_context(),
        )


def create_operation(
    session: Session,
    definition: OperationDefinition[Any],
) -> TaskOperation:
    """Create an operation from its declarative definition."""
    return OperationFactory.create(session, definition)
