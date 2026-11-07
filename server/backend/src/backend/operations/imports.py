from __future__ import annotations

from task_manager.scheduler.operation_factory import OperationDefinition

from backend.db.models import Collection, ImportRun

IMPORT_RUN_TASK_KEY = "import_run"
IMPORT_STEP_TASK_KEY = "import_adopt_files"


class ImportRunOperation(OperationDefinition[ImportRun]):
    kind = "import.run"
    resource_type = "system"
    task = IMPORT_RUN_TASK_KEY

    def __init__(self, run: ImportRun, *, importer_name: str) -> None:
        super().__init__(run)
        self.importer_name = importer_name

    @property
    def resource_id(self) -> int | None:
        # An import is about the whole installation; its run id travels in the task's arguments.
        return 0

    @property
    def title(self) -> str:
        return f"Import from {self.importer_name}"

    def task_kwargs(self) -> dict[str, object]:
        return {"import_run_id": self.resource.id}

    def context(self) -> dict[str, object]:
        return {"import_run_id": self.resource.id, "importer": self.resource.importer}


class ImportStepOperation(OperationDefinition[Collection]):
    kind = "import.adopt_files"
    resource_type = "collection"
    task = IMPORT_STEP_TASK_KEY

    def __init__(self, collection: Collection, *, step_id: int) -> None:
        super().__init__(collection)
        self.step_id = int(step_id)

    def task_kwargs(self) -> dict[str, object]:
        return {"import_step_id": self.step_id}

    def context(self) -> dict[str, object]:
        return {"collection_slug": self.resource.slug, "collection_title": self.resource.title,
                "import_step_id": self.step_id}
