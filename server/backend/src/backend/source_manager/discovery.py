"""Source-owned discovery declarations and opaque, runtime/account-scoped cursors."""
import hashlib
import json
import threading
import time

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from source_contracts import DomainCatalogue, SourceBrowseRequest, normalized_hostname

from backend.db import get_session
from backend.db.models.vodloft import Domain, SourceDomain
from backend.source_manager import secrets
from backend.source_manager.capabilities import effective, manifest_for
from backend.source_manager.connections import source_options
from backend.source_manager.gateway import SourceGateway, SourceInvocationError

_refreshed = 0.0
_refresh_lock = threading.Lock()


def remember_catalogue(session, source_id: str, catalogue: DomainCatalogue) -> None:
    for descriptor in catalogue.items:
        if descriptor.source_id != source_id:
            raise ValueError('Source catalogue returned a mismatched Source identity')
        domain = session.scalar(select(Domain).where(Domain.hostname == descriptor.hostname))
        if not domain:
            domain = Domain(hostname=descriptor.hostname, display_name=descriptor.display_name)
            session.add(domain)
            session.flush()
        support = session.scalar(select(SourceDomain).where(
            SourceDomain.domain_id == domain.id, SourceDomain.source_id == source_id))
        if not support:
            support = SourceDomain(domain_id=domain.id, source_id=source_id, support=descriptor.support)
            session.add(support)
        elif support.support != 'verified' or descriptor.support != 'advertised':
            support.support = descriptor.support
        support.aliases = descriptor.aliases
        support.capabilities = sorted(descriptor.capabilities) if descriptor.capabilities is not None else None
        support.catalogue_revision = catalogue.catalog_revision


def refresh_catalogues(gateway: SourceGateway | None = None) -> list:
    global _refreshed
    gateway = gateway or SourceGateway()
    manifests = gateway.manifests()
    if time.monotonic() - _refreshed < 60:
        return manifests
    # A catalogue refresh writes discovery declarations only, never media rows.
    if not _refresh_lock.acquire(blocking=False):
        return manifests
    try:
        for manifest in manifests:
            if 'domain_catalogue' not in manifest.capabilities:
                continue
            cursor, seen = None, set()
            try:
                for _ in range(20):
                    page = DomainCatalogue.model_validate(gateway.catalogue(manifest.source_id, cursor=cursor, limit=500))
                    with get_session() as session:
                        remember_catalogue(session, manifest.source_id, page)
                        session.commit()
                    if not page.next_cursor or page.next_cursor in seen:
                        break
                    cursor = page.next_cursor
                    seen.add(cursor)
            except (ValueError, RuntimeError, OSError):
                # Saved declarations remain available while a runtime is impaired.
                continue
        _refreshed = time.monotonic()
        return manifests
    finally:
        _refresh_lock.release()


def canonical_domain(session, source_id: str, hostname: str) -> str:
    hostname = normalized_hostname(hostname)
    for support, domain in session.execute(select(SourceDomain, Domain).join(
            Domain, Domain.id == SourceDomain.domain_id).where(SourceDomain.source_id == source_id)):
        if hostname == domain.hostname or hostname in (support.aliases or []):
            return domain.hostname
    return hostname


def _scope(gateway, source_id, connection_id, options, operation, arguments):
    command = gateway.commands.get(source_id)
    if not command:
        raise SourceInvocationError('unavailable', 'The selected Source runtime is unavailable')
    # Digests scope continuation to credentials without storing/exposing them.
    return {'operation': operation, 'source_id': source_id, 'connection_id': connection_id,
        'runtime': hashlib.sha256(json.dumps({'command': command,
            'manifest': manifest_for(source_id, gateway).model_dump(mode='json')}).encode()).hexdigest(),
        'connection': hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest(),
        'arguments': arguments}


def _unwrap(cursor, scope):
    if not cursor:
        return None
    try:
        value = json.loads(secrets.open_payload(cursor, ttl=3600))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError('This discovery continuation expired; start again') from exc
    if value.get('purpose') != 'source-discovery' or value.get('scope') != scope:
        raise ValueError('Source, Domain, runtime, account, or filters changed; start again')
    return value['cursor']


def _wrap(cursor, scope):
    return secrets.seal_payload(json.dumps({'purpose': 'source-discovery', 'scope': scope,
        'cursor': cursor}).encode()) if cursor else None


def search(source_id: str, query: str, *, domain: str | None = None, connection_id: int | None = None,
           cursor: str | None = None, limit: int = 30, job_id: int | None = None):
    gateway = SourceGateway()
    manifest = manifest_for(source_id, gateway)
    with get_session() as session:
        domain = canonical_domain(session, source_id, domain) if domain else None
        options = source_options(session, source_id, connection_id)
        policy = effective(session, source_id, domain, connection_id, manifest=manifest)
    if not manifest or 'search' not in manifest.capabilities or policy and 'search' not in policy.effective_capabilities:
        raise SourceInvocationError('unsupported_operation',
            policy.capability_reasons.get('search', 'Source search is unavailable') if policy else 'Source does not advertise search')
    scope = _scope(gateway, source_id, connection_id, options, 'search', {'query': query.strip(), 'domain': domain, 'limit': limit})
    result = gateway.search(source_id, query, domain=domain, cursor=_unwrap(cursor, scope), limit=limit, job_id=job_id, **options)
    if any(item.reference.source_id != source_id or domain is not None and item.reference.domain != domain for item in result.items):
        raise SourceInvocationError('runtime_error', 'Source returned invalid search provenance')
    return result.model_copy(update={'next_cursor': _wrap(result.next_cursor, scope)})


def browse(source_id: str, request: SourceBrowseRequest, *, connection_id: int | None = None, job_id: int | None = None):
    gateway = SourceGateway()
    manifest = manifest_for(source_id, gateway)
    with get_session() as session:
        domain = canonical_domain(session, source_id, request.domain)
        options = source_options(session, source_id, connection_id)
        policy = effective(session, source_id, domain, connection_id, manifest=manifest)
    if 'browse' not in policy.effective_capabilities:
        raise SourceInvocationError('unsupported_operation', policy.capability_reasons['browse'])
    scope = _scope(gateway, source_id, connection_id, options, 'browse', {
        'domain': domain, 'category_id': request.category_id, 'limit': request.limit})
    result = gateway.browse(source_id, request.model_copy(update={
        'domain': domain, 'cursor': _unwrap(request.cursor, scope)}), job_id=job_id, **options)
    if result.domain != domain or any(item.reference.source_id != source_id for item in result.items):
        raise SourceInvocationError('runtime_error', 'Source returned invalid browse provenance')
    return result.model_copy(update={'next_cursor': _wrap(result.next_cursor, scope)})


def entries(source_id: str, url: str, *, connection_id: int | None = None,
            cursor: str | None = None, limit: int = 50):
    """Preview membership; continuation never crosses a runtime or account."""
    from urllib.parse import urlsplit
    gateway = SourceGateway()
    manifest = manifest_for(source_id, gateway)
    with get_session() as session:
        domain = canonical_domain(session, source_id, urlsplit(url).hostname or '')
        options = source_options(session, source_id, connection_id)
        policy = effective(session, source_id, domain, connection_id, manifest=manifest)
    if 'enumerate_collection' not in policy.effective_capabilities:
        raise SourceInvocationError('unsupported_operation', policy.capability_reasons['enumerate_collection'])
    scope = _scope(gateway, source_id, connection_id, options, 'entries', {'url': url, 'limit': limit})
    result = gateway.entries(source_id, url, cursor=_unwrap(cursor, scope), limit=limit, **options)
    if any(entry.reference.source_id != source_id for entry in result.entries):
        raise SourceInvocationError('runtime_error', 'Source returned invalid membership provenance')
    return result.model_copy(update={'next_cursor': _wrap(result.next_cursor, scope)})
