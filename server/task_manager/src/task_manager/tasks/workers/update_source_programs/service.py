from __future__ import annotations

import logging

from config.network import is_no_internet_error
from sources import Feature, all_sources
from task_manager.scheduler.results import TaskResult

logger = logging.getLogger(__name__)


def run_update_source_programs() -> TaskResult:
    """Update each Source's program once its weekly update is due."""
    updated: list[str] = []
    failed: list[str] = []
    for source in all_sources():
        if not source.has(Feature.PROGRAM_UPDATES) or not source.program_update_due():
            continue
        try:
            status = source.update_program()
        except Exception as exc:
            if is_no_internet_error(exc):
                raise
            logger.warning("Could not update %s: %s", source.name, exc)
            failed.append(source.name)
            continue
        updated.append(f"{status.name} {status.version or ''}".strip())
    if failed:
        raise RuntimeError(f"Could not update {', '.join(failed)}")
    summary = f"Updated {', '.join(updated)}" if updated else "Everything is up to date"
    return TaskResult(summary=summary, data={"updated": updated})
