from __future__ import annotations

from collections.abc import Sequence

from backend.db.models import Creator
from sources import Names
from task_manager.scheduler.db import TaskOperation
from task_manager.scheduler.operation_factory import OperationDefinition
from task_manager.scheduler.operations import OperationDependencySpec, OperationTargetSpec


class CreatorMoveSectionsOperation(OperationDefinition[Creator]):
    """Moving a creator's feeds and lists from its Edit page, as one action. Everything the move starts is a part of
    it: the operations it created, such as numbering a collection's episodes again and indexing a new collection, and
    the tasks it queued, such as deleting the files of what left the Library, which run as its own targets. Its
    progress is theirs together."""

    kind = "creator.move_sections"
    resource_type = "creator"

    def __init__(
            self, creator: Creator, *, parts: Sequence[TaskOperation], tasks: Sequence[OperationTargetSpec],
            sections: Sequence[str], names: Names,
    ) -> None:
        super().__init__(creator)
        self.parts = list(parts)
        self.tasks = list(tasks)
        self.sections = list(sections)
        self.names = names

    def targets(self) -> tuple[OperationTargetSpec, ...]:
        return tuple(self.tasks)

    def dependencies(self) -> tuple[OperationDependencySpec, ...]:
        return tuple(
            OperationDependencySpec(child_operation_id=part.id, slot_key=f"{part.kind}:{part.resource_id}")
            for part in self.parts
        )

    def context(self) -> dict[str, object]:
        # The feeds and lists that moved, as "<account id>:<ref>", and what they are together, such as "shorts and
        # playlists", for the UI to name the action by.
        return {
            "creator_slug": self.resource.slug, "creator_title": self.resource.title, "sections": self.sections,
            "names": {"singular": self.names.singular, "plural": self.names.plural, "a": self.names.a},
        }
