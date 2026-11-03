from __future__ import annotations

import asyncio

from controller.db_utils import db_session
from task_manager.scheduler.registry import task
from task_manager.scheduler.results import TaskResult


def _run(import_run_id: int) -> TaskResult:
    from backend.db.models import ImportRun
    from backend.services.imports import WAITING, apply_run

    with db_session() as session:
        counts = apply_run(session, import_run_id)
        run = session.get(ImportRun, import_run_id)
        waits_for_indexing = run is not None and run.status == WAITING
    created = counts.get("collections_created", 0)
    linked = counts.get("collections_linked", 0)
    # An import that brings its episodes along, such as WireLoft's, adopts its files right away.
    files = (
        "their files are adopted once they are indexed" if waits_for_indexing
        else f"adopted {counts.get('adopted', 0)} downloaded file(s)"
    )
    return TaskResult(
        summary=f"Imported {created} new collection(s) and linked {linked}; {files}",
        data=counts,
    )


def _adopt(import_step_id: int) -> TaskResult:
    from backend.services.imports import fail_step, run_step

    try:
        with db_session() as session:
            counts = run_step(session, import_step_id)
    except Exception as exc:
        # The files adopted so far stay adopted; the import shows this Collection as failed instead of waiting.
        with db_session() as session:
            fail_step(session, import_step_id, str(exc))
        raise
    return TaskResult(
        summary=f"Adopted {counts.get('adopted', 0)} file(s), {counts.get('not_adopted', 0)} could not be adopted",
        data=counts,
    )


@task(
    key="import_run",
    title="Import",
    description="Apply an import from another program: settings, profiles, collections and Download Profiles.",
    allowed_resource_types=("system",),
    default_max_retries=0,
)
async def import_run(*, import_run_id: int | None = None, **_kwargs) -> TaskResult:
    if import_run_id is None:
        raise ValueError("An import needs its run")
    return await asyncio.to_thread(_run, import_run_id)


@task(
    key="import_adopt_files",
    title="Adopt imported files",
    description="Number and adopt the files another program downloaded for a collection, once it is indexed.",
    allowed_resource_types=("collection",),
    default_max_retries=0,
)
async def import_adopt_files(*, import_step_id: int | None = None, **_kwargs) -> TaskResult:
    if import_step_id is None:
        raise ValueError("Adopting imported files needs the import step")
    return await asyncio.to_thread(_adopt, import_step_id)
