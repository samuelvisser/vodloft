"""Bounded, durable Collection synchronization through the private Source client."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import threading
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.vodloft import CollectionEntry, CollectionScan, Domain, MediaItem, SourceConnection, SourceReference
from backend.services.vodloft_imports import reconcile_members, store_snapshot
from backend.source_manager.connections import source_options, connection_fingerprint as account_fingerprint
from backend.source_manager.gateway import SourceGateway, SourceInvocationError, cancel_running_job, clear_canceled_job
from backend.source_manager.runtime import command_for
from backend.source_manager.concurrency import try_acquire, release
from task_manager.scheduler.db import TaskOperation

LEASE_SECONDS = 300
FULL_SCAN_INTERVAL = timedelta(hours=24)
_dispatch_slots = threading.BoundedSemaphore(2)
logger = logging.getLogger(__name__)


class CollectionSyncError(ValueError):
    pass


class CollectionSyncBusy(CollectionSyncError):
    pass


@dataclass(frozen=True)
class ScanResult:
    scan_id: int
    collection_id: int
    operation_id: str
    status: str
    complete: bool
    entry_count: int
    removed_count: int
    error: str | None


def _utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def _fingerprint(value) -> str:
    # Account values affect cursor scope, but only a one-way digest is persisted.
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _result(scan) -> ScanResult:
    return ScanResult(scan.id, scan.collection_id, scan.operation_id, scan.status,
        scan.complete, scan.entry_count, scan.removed_count, scan.error)


def _lease(session, scan_id: int, owner: str) -> CollectionScan:
    now = datetime.now(timezone.utc)
    changed = session.execute(update(CollectionScan).where(
        CollectionScan.id == scan_id, CollectionScan.lease_owner == owner,
        CollectionScan.active_reference_id.is_not(None)).values(
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), updated_at=now))
    if not changed.rowcount:
        raise CollectionSyncBusy('This scan was canceled or another worker owns it')
    scan = session.get(CollectionScan, scan_id, populate_existing=True)
    if scan.connection_fingerprint != account_fingerprint(session, scan.source_id, scan.connection_id, lock=True):
        raise SourceInvocationError('unavailable', 'Source account changed; restart this bounded scan')
    operation = session.get(TaskOperation, scan.operation_id)
    if operation and operation.status == 'CANCELED':
        raise CollectionSyncBusy('Collection refresh was canceled')
    return scan


def _operation(session, scan: CollectionScan, *, terminal: bool = False, defer_terminal: bool = False) -> None:
    operation = session.get(TaskOperation, scan.operation_id)
    if not operation:
        return
    if operation.status == 'CANCELED':
        return
    operation.status = ('RUNNING' if defer_terminal else 'SUCCEEDED' if scan.complete else 'CANCELED' if scan.status == 'canceled'
        else 'FAILED' if scan.status in {'failed', 'abandoned'} else 'PARTIAL' if terminal else 'RUNNING')
    # Enumeration has an unknown total. The UI displays the reported count and
    # working state, rather than inventing a percentage for a growing archive.
    operation.progress = 100 if scan.complete and not defer_terminal else None
    operation.message = (f'{scan.entry_count} members checked; {scan.removed_count} memberships removed'
        if scan.complete else f'{scan.entry_count} members checked' + ('; continuation saved' if terminal else ''))
    operation.context = {**(operation.context or {}), 'scan_id': scan.id,
        'scanned_items': scan.entry_count, 'scan_mode': scan.mode, 'tracks_progress': False,
        'source_reference_id': (operation.context or {}).get('source_reference_id', scan.source_reference_id)}
    operation.error = scan.error
    operation.finished_at = datetime.now(timezone.utc) if terminal and not defer_terminal else None
    if terminal and not defer_terminal:
        operation.result = {'summary': operation.message, 'data': {
            'item_id': scan.collection_id, 'complete': scan.complete,
            'entry_count': scan.entry_count, 'removed_count': scan.removed_count}}


def synchronize(collection_id: int, reference_id: int | None = None, *,
                full: bool | None = None, max_pages: int = 100,
                gateway: SourceGateway | None = None, operation_id: str | None = None,
                defer_terminal: bool = False) -> ScanResult:
    """Commit each page, resume full scans, and reconcile only after all pages.

    Automatic refreshes inspect the leading pages frequently and do a full
    reconciliation at least daily. Full scans longer than the page budget resume
    with the same scan key, so membership seen on earlier pages stays present.
    """
    if not 1 <= max_pages <= 100:
        raise CollectionSyncError('Choose between one and 100 scan pages')
    with get_session() as session:
        item = session.get(MediaItem, collection_id)
        if not item or item.kind != 'collection':
            raise CollectionSyncError('Collection not found')
        references = [r for r in session.scalars(select(SourceReference).where(
            SourceReference.item_id == collection_id)).all() if r.connection_id is None or
            (session.get(SourceConnection, r.connection_id) and session.get(SourceConnection, r.connection_id).enabled)]
        reference = next((r for r in references if r.id == reference_id), None) if reference_id is not None else (
            references[0] if len(references) == 1 else None)
        if not reference:
            raise CollectionSyncError('Select an available Source/account reference for this Collection')
        source_id, url, connection_id, reference_id = reference.source_id, reference.url, reference.connection_id, reference.id
        expected = (session.get(Domain, reference.domain_id).hostname, reference.namespace, reference.upstream_id)
        options = source_options(session, source_id, connection_id)
        connection_fingerprint = account_fingerprint(session, source_id, connection_id)
        title = item.user_title or item.title
    gateway = gateway or SourceGateway()
    command = gateway.commands.get(source_id)
    if not command:
        raise CollectionSyncError('The selected Source runtime is unavailable')
    # Freeze one runtime for resolution and all pages in this dispatch.
    gateway = SourceGateway({source_id: list(command)})
    manifest = next(iter(gateway.manifests()), None)
    if manifest is None:
        raise CollectionSyncError('The selected Source runtime is unavailable')
    runtime_version = manifest.version
    try:
        active_command, active_version = command_for(source_id)
        if active_command == command:
            runtime_version = active_version
    except (ValueError, RuntimeError):
        pass
    command_fingerprint = _fingerprint({'command': command, 'runtime': runtime_version,
        'protocol': manifest.protocol_version, 'catalogue_revision': manifest.catalogue_revision})
    owner, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    with get_session() as session:
        scan = session.scalar(select(CollectionScan).where(CollectionScan.active_reference_id == reference_id))
        if scan and scan.lease_expires_at and _utc(scan.lease_expires_at) > now:
            raise CollectionSyncBusy('A refresh for this Source/account is already running')
        if scan and (scan.command_fingerprint != command_fingerprint or
                     scan.connection_fingerprint != connection_fingerprint):
            scan.status, scan.error, scan.active_reference_id = 'abandoned', 'Source runtime or account changed; restarted from the beginning', None
            _operation(session, scan, terminal=True)
            session.flush()
            scan = None
        if scan:
            changed = session.execute(update(CollectionScan).where(CollectionScan.id == scan.id,
                or_(CollectionScan.lease_expires_at.is_(None), CollectionScan.lease_expires_at <= now)).values(
                    lease_owner=owner, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), status='running'))
            if not changed.rowcount:
                raise CollectionSyncBusy('Another worker resumed this refresh')
            session.refresh(scan)
            if session.get(TaskOperation, scan.operation_id).status in {'PARTIAL', 'FAILED'}:
                scan.operation_id = None
        else:
            previous_full = session.scalar(select(CollectionScan).where(
                CollectionScan.source_reference_id == reference_id, CollectionScan.complete.is_(True),
                CollectionScan.mode == 'full').order_by(CollectionScan.id.desc()))
            full = full if full is not None else (not previous_full or now - _utc(previous_full.updated_at) >= FULL_SCAN_INTERVAL)
            scan = CollectionScan(collection_id=collection_id, source_reference_id=reference_id,
                active_reference_id=reference_id, source_id=source_id, connection_id=connection_id,
                scan_key=str(uuid.uuid4()), mode='full' if full else 'incremental', status='running',
                runtime_version=runtime_version, command_fingerprint=command_fingerprint,
                connection_fingerprint=connection_fingerprint, lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), complete=False, entry_count=0)
            session.add(scan)
        if operation_id is not None:
            operation = session.get(TaskOperation, operation_id)
            if not operation or operation.status == 'CANCELED':
                raise CollectionSyncError('Collection refresh was canceled')
            scan.operation_id = operation_id
        if not scan.operation_id:
            operation = TaskOperation(id=str(uuid.uuid4()), kind='vodloft_collection_sync', source='SYSTEM',
                resource_type='vodloft_media', resource_id=collection_id, title=title[:255],
                status='RUNNING', progress=None, message='Inspecting Collection', started_at=now,
                context={'tracks_progress': False, 'source_id': source_id, 'source_reference_id': reference_id})
            session.add(operation)
            scan.operation_id = operation.id
        scan.error = None
        scan.error_code, scan.retry_at = None, None
        scan.attempts = (scan.attempts or 0) + 1
        try:
            session.flush()
            operation = session.get(TaskOperation, scan.operation_id)
            operation.context = {**(operation.context or {}), 'stage': 'resolving'}
            session.commit()
        except IntegrityError as exc:
            raise CollectionSyncBusy('Another worker started this Source/account refresh') from exc
        scan_id, scan_key, cursor, mode = scan.id, scan.scan_key, scan.next_cursor, scan.mode
    clear_canceled_job(-scan_id)
    try:
        snapshot = gateway.resolve(source_id, url, max_entries=1 if 'enumerate_pages' in manifest.capabilities else 100,
            job_id=-scan_id, **options)
        if snapshot.kind != 'collection':
            raise CollectionSyncError('Source no longer identifies this URL as a Collection')
        if (snapshot.reference.domain, snapshot.reference.namespace, snapshot.reference.upstream_id) != expected:
            raise SourceInvocationError('unavailable', 'Source changed the Collection identity; resolve and review it again')
        store_snapshot(snapshot.model_copy(update={'entries': [], 'enumeration_complete': False}), connection_id,
            scan_key=scan_key, runtime_version=runtime_version, reconcile=False, record_scan=False,
            lease_scan_id=scan_id, lease_owner=owner)
        budget = max_pages if mode == 'full' else min(max_pages, 2)
        seen_cursors, complete = set(), False
        for _ in range(budget):
            with get_session() as session:
                scan = _lease(session, scan_id, owner)
                operation = session.get(TaskOperation, scan.operation_id)
                operation.context = {**(operation.context or {}), 'stage': 'enumerating'}
                session.commit()
            if 'enumerate_pages' in manifest.capabilities:
                page = gateway.entries(source_id, url, cursor=cursor, limit=50, job_id=-scan_id, **options)
                entries, next_cursor, complete = page.entries, page.next_cursor, page.complete
            else:
                entries, next_cursor, complete = snapshot.entries, None, snapshot.enumeration_complete
            if not complete and next_cursor and (next_cursor == cursor or next_cursor in seen_cursors):
                raise SourceInvocationError('runtime_error', 'Source returned a repeated Collection cursor')
            store_snapshot(snapshot.model_copy(update={'entries': entries, 'enumeration_complete': False}), connection_id,
                scan_key=scan_key, runtime_version=runtime_version, reconcile=False, record_scan=False,
                lease_scan_id=scan_id, lease_owner=owner)
            with get_session() as session:
                scan = _lease(session, scan_id, owner)
                scan.entry_count = session.scalar(select(func.count()).select_from(CollectionEntry).where(
                    CollectionEntry.collection_id == collection_id, CollectionEntry.last_seen_scan_key == scan_key))
                scan.next_cursor = None if complete else next_cursor
                _operation(session, scan)
                session.commit()
            if complete:
                break
            if not next_cursor:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        with get_session() as session:
            scan = _lease(session, scan_id, owner)
            if complete:
                scan.removed_count = reconcile_members(session, collection_id, source_id, connection_id, scan_key)
                scan.complete, scan.status, scan.active_reference_id = True, 'complete', None
            elif mode == 'full' and scan.next_cursor:
                scan.status = 'paused'
            else:
                scan.status, scan.active_reference_id = 'partial', None
            scan.lease_owner, scan.lease_expires_at = None, None
            scan.error = None
            scan.failure_count = 0
            scan.retry_at = datetime.now(timezone.utc) + timedelta(minutes=5) if scan.status == 'paused' else None
            _operation(session, scan, terminal=True, defer_terminal=defer_terminal)
            session.commit()
            return _result(scan)
    except Exception as exc:
        with get_session() as session:
            scan = session.get(CollectionScan, scan_id)
            if not scan or scan.lease_owner != owner:
                raise
            canceled = session.get(TaskOperation, scan.operation_id).status == 'CANCELED'
            reason = exc.code if isinstance(exc, SourceInvocationError) else 'runtime_error'
            scan.failure_count = (scan.failure_count or 0) + 1
            scan.error_code = reason
            scan.retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(3600,
                (300 if reason == 'rate_limited' else 60) * 2 ** min(scan.failure_count - 1, 6)))) if (
                not canceled and reason in {'unavailable', 'rate_limited', 'runtime_error'} and scan.failure_count < 5) else None
            scan.status, scan.error = ('canceled', 'Collection refresh canceled') if canceled else (
                'failed', f"Collection {(session.get(TaskOperation, scan.operation_id).context or {}).get('stage', 'resolving')} stopped ({reason}); known members were preserved")
            # Retry a full scan only at the last committed cursor. Incremental
            # scans start again from the beginning to pick up new leading items.
            if canceled or mode != 'full':
                scan.active_reference_id = None
            scan.lease_owner, scan.lease_expires_at = None, None
            scan.updated_at = datetime.now(timezone.utc)
            _operation(session, scan, terminal=True, defer_terminal=defer_terminal and not canceled)
            session.commit()
            return _result(scan)
    finally:
        clear_canceled_job(-scan_id)


def cancel_scan(collection_id: int, scan_id: int) -> None:
    with get_session() as session:
        scan = session.get(CollectionScan, scan_id)
        if not scan or scan.collection_id != collection_id:
            raise CollectionSyncError('Collection scan not found')
        if scan.complete or scan.active_reference_id is None:
            return
        operation_id = scan.operation_id
    cancel_operation(operation_id)


def cancel_operation(operation_id: str) -> None:
    with get_session() as session:
        operation = session.get(TaskOperation, operation_id)
        if not operation or operation.kind != 'vodloft_collection_sync':
            raise CollectionSyncError('Collection operation not found')
        if operation.status in {'SUCCEEDED', 'CANCELED'}:
            return
        scan_ids = []
        for scan in session.scalars(select(CollectionScan).where(CollectionScan.operation_id == operation_id,
                CollectionScan.active_reference_id.is_not(None))):
            scan.status, scan.active_reference_id, scan.retry_at = 'canceled', None, None
            scan.error = 'Collection refresh canceled'
            scan_ids.append(scan.id)
        operation.status, operation.message = 'CANCELED', 'Collection refresh canceled'
        operation.finished_at = datetime.now(timezone.utc)
        session.commit()
    for scan_id in scan_ids:
        cancel_running_job(-scan_id)


def restart_operation(operation_id: str) -> str:
    with get_session() as session:
        operation = session.get(TaskOperation, operation_id)
        if not operation or operation.kind != 'vodloft_collection_sync' or operation.status not in {'FAILED', 'PARTIAL', 'CANCELED'}:
            raise CollectionSyncError('Only a failed, partial or canceled refresh can be resumed')
        collection_id, context = operation.resource_id, dict(operation.context or {})
    return enqueue(collection_id, context.get('source_reference_id'), full=context.get('full_scan', True),
        expand_depth=context.get('expand_depth', 0), max_nested=context.get('max_nested', 20))


def enqueue(collection_id: int, reference_id: int | None = None, *, full: bool | None = True,
            expand_depth: int = 0, max_nested: int = 20, source: str = 'UI') -> str:
    """Persist user intent before responding or starting any upstream work."""
    if not 0 <= expand_depth <= 3 or not 1 <= max_nested <= 25:
        raise CollectionSyncError('Choose up to three nested levels and 25 nested Collections')
    with get_session() as session:
        item = session.get(MediaItem, collection_id)
        if not item or item.kind != 'collection':
            raise CollectionSyncError('Collection not found')
        references = session.scalars(select(SourceReference).where(SourceReference.item_id == collection_id)).all()
        reference = next((r for r in references if r.id == reference_id), None) if reference_id is not None else (
            references[0] if len(references) == 1 else None)
        if not reference:
            raise CollectionSyncError('Select a Source/account reference for this Collection')
        if source == 'SYSTEM' and full is None:
            pending = session.scalar(select(CollectionScan).where(CollectionScan.active_reference_id == reference.id))
            try:
                current_runtime = command_for(reference.source_id)[1]
            except (ValueError, RuntimeError):
                current_runtime = None
            scope_unchanged = pending and pending.runtime_version == current_runtime and (
                pending.connection_fingerprint == account_fingerprint(session, reference.source_id, reference.connection_id))
            if scope_unchanged and pending.status == 'failed' and (pending.retry_at is None or _utc(pending.retry_at) > datetime.now(timezone.utc)):
                return pending.operation_id
        for operation in session.scalars(select(TaskOperation).where(
                TaskOperation.kind == 'vodloft_collection_sync', TaskOperation.resource_id == collection_id,
                TaskOperation.status.in_(['QUEUED', 'RUNNING', 'WAITING']))).all():
            if (operation.context or {}).get('source_reference_id') == reference.id:
                return operation.id
        operation = TaskOperation(id=str(uuid.uuid4()), kind='vodloft_collection_sync', source=source,
            resource_type='vodloft_media', resource_id=collection_id, title=(item.user_title or item.title)[:255],
            status='QUEUED', progress=None, message='Collection refresh queued', context={
                'source_reference_id': reference.id, 'full_scan': full,
                'expand_depth': expand_depth, 'max_nested': max_nested, 'tracks_progress': False})
        session.add(operation)
        session.commit()
        return operation.id


def _expand(collection_id: int, reference_id: int, depth: int, max_nested: int, operation_id: str) -> list[dict]:
    from backend.services.vodloft_collections import source_memberships
    visited, refreshed, issues = {collection_id}, [], []

    def visit(parent_id, parent_reference_id, level):
        if level >= depth:
            return
        with get_session() as session:
            parent = session.get(SourceReference, parent_reference_id)
            children = []
            if not parent:
                return
            for entry in source_memberships(session, parent_id, parent.source_id, parent.connection_id):
                child = session.get(MediaItem, entry.item_id)
                if not child or child.kind != 'collection':
                    continue
                references = session.scalars(select(SourceReference).where(
                    SourceReference.item_id == child.id, SourceReference.source_id == parent.source_id,
                    SourceReference.connection_key == (parent.connection_id or 0))).all()
                children.append((child.id, references[0].id if len(references) == 1 else None))
        for child_id, child_reference in children:
            with get_session() as session:
                operation = session.get(TaskOperation, operation_id)
                if not operation or operation.status == 'CANCELED':
                    return
            if child_id in visited:
                issues.append({'item_id': child_id, 'reason': 'Collection cycle or repeated reference'})
                continue
            visited.add(child_id)
            if child_reference is None or len(refreshed) >= max_nested:
                issues.append({'item_id': child_id, 'reason': 'No unambiguous account reference or nested limit reached'})
                continue
            try:
                with get_session() as session:
                    reference = session.get(SourceReference, child_reference)
                    child_slots = try_acquire(reference.source_id,
                        session.get(Domain, reference.domain_id).hostname, reference.connection_id)
                if child_slots is None:
                    issues.append({'item_id': child_id, 'reason': 'Nested Source/account is busy; resume the refresh later'})
                    continue
                try:
                    result = synchronize(child_id, child_reference, full=True, operation_id=operation_id, defer_terminal=True)
                finally:
                    release(child_slots)
                refreshed.append(child_id)
                if not result.complete:
                    issues.append({'item_id': child_id, 'reason': result.error or 'Nested continuation saved'})
                visit(child_id, child_reference, level + 1)
            except (CollectionSyncError, ValueError):
                issues.append({'item_id': child_id, 'reason': 'Nested Source/account could not be refreshed'})

    visit(collection_id, reference_id, 0)
    return issues


def dispatch_queued(on_complete=None) -> None:
    """Recover persisted intents and run bounded scans without blocking sweeps."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        pending = session.scalars(select(CollectionScan).where(
            CollectionScan.active_reference_id.is_not(None), CollectionScan.status.in_(['paused', 'failed', 'running']),
            or_(CollectionScan.lease_expires_at.is_(None), CollectionScan.lease_expires_at <= now),
            or_(CollectionScan.status == 'running', CollectionScan.retry_at <= now)).limit(20)).all()
        resumable = [(s.collection_id, s.source_reference_id) for s in pending]
    for collection_id, reference_id in resumable:
        enqueue(collection_id, reference_id, full=True, source='SYSTEM')
    with get_session() as session:
        queued = session.scalars(select(TaskOperation).where(
            TaskOperation.kind == 'vodloft_collection_sync', or_(TaskOperation.status == 'QUEUED',
                (TaskOperation.status == 'RUNNING') &
                (TaskOperation.updated_at <= now - timedelta(seconds=LEASE_SECONDS))))
            .order_by(TaskOperation.created_at).limit(20)).all()
        operation_ids = [operation.id for operation in queued]
    for operation_id in operation_ids:
        if not _dispatch_slots.acquire(blocking=False):
            break
        with get_session() as session:
            operation = session.get(TaskOperation, operation_id)
            reference = session.get(SourceReference, (operation.context or {}).get('source_reference_id')) if operation else None
            upstream = try_acquire(reference.source_id,
                session.get(Domain, reference.domain_id).hostname, reference.connection_id) if reference else []
            if upstream is None:
                _dispatch_slots.release()
                continue
            claimed = session.execute(update(TaskOperation).where(TaskOperation.id == operation_id,
                or_(TaskOperation.status == 'QUEUED', (TaskOperation.status == 'RUNNING') &
                    (TaskOperation.updated_at <= now - timedelta(seconds=LEASE_SECONDS)))).values(
                        status='RUNNING', started_at=now, updated_at=now))
            session.commit()
            if not claimed.rowcount:
                release(upstream)
                _dispatch_slots.release()
                continue
            operation = session.get(TaskOperation, operation_id)
            collection_id, context = operation.resource_id, dict(operation.context or {})

        def run(operation_id=operation_id, collection_id=collection_id, context=context, upstream=upstream):
            try:
                result = synchronize(collection_id, context['source_reference_id'],
                    full=context.get('full_scan'), operation_id=operation_id, defer_terminal=True)
                # Nested Collections can belong to another Domain. Release the
                # parent's slots so each child acquires its own scoped limits.
                release(upstream)
                upstream = []
                issues = []
                if context.get('expand_depth') and result.complete:
                    issues = _expand(collection_id, context['source_reference_id'],
                        context['expand_depth'], context['max_nested'], operation_id)
                with get_session() as session:
                    operation = session.get(TaskOperation, operation_id)
                    if operation and operation.status != 'CANCELED':
                        operation.status = 'FAILED' if result.error else 'SUCCEEDED' if result.complete and not issues else 'PARTIAL'
                        operation.progress = 100 if operation.status == 'SUCCEEDED' else None
                        operation.message = f'{result.entry_count} members checked; {result.removed_count} memberships removed'
                        operation.error = result.error
                        operation.result = {'summary': operation.message, 'data': {
                            'item_id': collection_id, 'complete': result.complete,
                            'entry_count': result.entry_count, 'removed_count': result.removed_count, 'nested_issues': issues}}
                        operation.finished_at = datetime.now(timezone.utc)
                        session.commit()
                if on_complete is not None and result.status != 'canceled':
                    try:
                        on_complete(result)
                    except Exception:
                        logger.warning('Collection follow-up scheduling needs a later sweep for item %s', collection_id)
            except Exception as exc:
                # Do not expose upstream exceptions, URLs or account values.
                with get_session() as session:
                    operation = session.get(TaskOperation, operation_id)
                    if operation and operation.status != 'CANCELED':
                        operation.status, operation.error = 'FAILED', 'Collection refresh could not start; check the selected Source/account'
                        pending = session.scalar(select(CollectionScan).where(
                            CollectionScan.active_reference_id == context.get('source_reference_id')))
                        reference = session.get(SourceReference, context.get('source_reference_id'))
                        if pending is None and reference:
                            try:
                                runtime_version = command_for(reference.source_id)[1]
                            except (ValueError, RuntimeError):
                                runtime_version = None
                            # Failures before resolution still own a durable scan
                            # record and the same bounded automatic retry budget.
                            pending = CollectionScan(collection_id=collection_id,
                                source_reference_id=reference.id, active_reference_id=reference.id,
                                source_id=reference.source_id, connection_id=reference.connection_id,
                                connection_fingerprint=account_fingerprint(session, reference.source_id, reference.connection_id),
                                runtime_version=runtime_version, scan_key=str(uuid.uuid4()), mode='full',
                                status='failed', complete=False, entry_count=0, attempts=0, failure_count=0)
                            session.add(pending)
                        if pending and pending.operation_id != operation_id:
                            pending.operation_id, pending.status = operation_id, 'failed'
                            pending.error, pending.error_code = operation.error, exc.code if isinstance(exc, SourceInvocationError) else 'unavailable'
                            pending.attempts = (pending.attempts or 0) + 1
                            pending.failure_count = (pending.failure_count or 0) + 1
                            pending.retry_at = (datetime.now(timezone.utc) + timedelta(seconds=min(3600, 300 * 2 ** pending.failure_count))) if (
                                pending.failure_count < 5 and pending.error_code in {'unavailable', 'rate_limited', 'runtime_error'}) else None
                            pending.updated_at = datetime.now(timezone.utc)
                            session.flush()
                            operation.context = {**(operation.context or {}), 'scan_id': pending.id,
                                'stage': 'resolving', 'error_code': pending.error_code}
                            operation.message = f'Collection resolving stopped ({pending.error_code}); known members were preserved'
                        operation.finished_at = datetime.now(timezone.utc)
                        session.commit()
            finally:
                release(upstream)
                _dispatch_slots.release()

        threading.Thread(target=run, name=f'vodloft-sync-{operation_id}', daemon=True).start()
