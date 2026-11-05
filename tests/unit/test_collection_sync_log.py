"""A Collection's Sync log lists only the scans that looked at it, and Sync now runs the scan its Source gets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from test_quick_check import _collection, listed_too, quick, session  # noqa: F401

def _definitions(session):
    from task_manager.scheduler.db import TaskDefinition

    keys = ("fetch_new_episodes", "rescan_quick_checked_collections", "quick_check_new_videos")
    definitions = {key: TaskDefinition(key=key, title=key) for key in keys}
    session.add_all(definitions.values())
    session.commit()
    return definitions

def _run(session, definition, *, minute: int, status: str = "SUCCEEDED", resource_id=None, resource_type="collection", collections=None):
    from task_manager.scheduler.db import TaskRun
    from task_manager.scheduler.types import ResourceType, TaskStatus

    at = datetime(2026, 11, 5, 18, tzinfo=timezone.utc) + timedelta(minutes=minute)
    run = TaskRun(
        definition=definition, resource_type=ResourceType(resource_type), resource_id=resource_id,
        status=TaskStatus(status), started_at=at, finished_at=at, created_at=at,
        result=None if collections is None else {"summary": "", "data": {"collections": collections}},
    )
    session.add(run)
    session.commit()
    return run

def test_the_sync_log_lists_only_scans_that_looked_at_the_collection(quick, listed_too, session):
    from backend.api.endpoints.collections.sync_log import collection_scans

    channel = _collection(session, "UC1")
    playlist = _collection(session, "PL1", source_key="listed")
    tasks = _definitions(session)
    _run(session, tasks["fetch_new_episodes"], minute=0, collections=[{"collection_id": playlist.id, "episodes_found": 2}])
    _run(session, tasks["fetch_new_episodes"], minute=1, status="FAILED")
    quick_check = _run(
        session, tasks["quick_check_new_videos"], minute=2, resource_type="system", resource_id=0,
        collections=[{"collection_id": channel.id, "episodes_found": 0}],
    )
    failed_check = _run(
        session, tasks["quick_check_new_videos"], minute=3, resource_type="system", resource_id=0,
        collections=[{"collection_id": channel.id, "episodes_found": None, "failed": True}],
    )
    _run(session, tasks["quick_check_new_videos"], minute=4, resource_type="system", resource_id=0, collections=[])
    rescan = _run(
        session, tasks["rescan_quick_checked_collections"], minute=5, resource_id=channel.id,
        collections=[{"collection_id": channel.id, "episodes_found": 3}],
    )

    scans, total = collection_scans(session, "UC1", offset=0, limit=10)

    assert total == 3
    assert [(scan.id, scan.kind, scan.status, scan.episodes_found) for scan in scans] == [
        (rescan.id, "full_scan", "SUCCEEDED", 3),
        (failed_check.id, "quick_check", "FAILED", None),
        (quick_check.id, "quick_check", "SUCCEEDED", 0),
    ]
    assert collection_scans(session, "UC1", offset=2, limit=10)[0][0].id == quick_check.id

def test_sync_now_runs_the_scan_the_regular_checks_give_the_collection(quick, listed_too, session):
    from backend.api.endpoints.collections.operations import CollectionSyncOperation

    assert CollectionSyncOperation(_collection(session, "UC1")).task == "rescan_quick_checked_collections"
    assert CollectionSyncOperation(_collection(session, "PL1", source_key="listed")).task == "fetch_new_episodes"
