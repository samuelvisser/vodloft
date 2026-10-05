"""Generic Source browsing, inspection, and safe public transport aliases."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AliasGenerator, AliasPath, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from source_contracts import (SourceBrowseRequest, SourceBrowsePage, SourceConnectionStatus,
    NormalizedSnapshot, SourceError, SourceMediaReference, normalized_hostname)

from backend.db import get_session
from backend.db.models.vodloft import AcquisitionJob, Domain, SourceConnection, SourceDomain, SourceReference
from backend.security.permissions import principal, require_connection
from backend.source_manager import discovery, secrets
from backend.source_manager.capabilities import EffectiveCapabilities, effective, manifest_for
from backend.source_manager.connections import source_options
from backend.source_manager.gateway import SourceGateway, SourceInvocationError

router = APIRouter(prefix='/vodloft', tags=['VodLoft discovery'])


def _failure(exc):
    if isinstance(exc, SourceInvocationError):
        error = SourceError(code=exc.code, message=str(exc))
        status = {'unsupported_operation': 422, 'authentication_required': 409,
            'rate_limited': 429, 'unavailable': 503}.get(exc.code, 502)
    elif isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
        error = SourceError(code='invalid_url', message=str(exc))
        status = 422
    else:
        error = SourceError(code='runtime_error', message='Source returned an invalid response or is temporarily unavailable')
        status = 502
    # The detail string keeps normal form handling, alongside the typed envelope.
    return JSONResponse(status_code=status, content={'detail': error.message, 'error': error.model_dump(mode='json')},
        headers={'X-VodLoft-Source-Error': error.code})


@dataclass(frozen=True)
class DomainSourceView:
    declaration: SourceDomain
    policy: EffectiveCapabilities
    display_name: str


def _source_alias(name):
    if name in {'source_id', 'support', 'aliases'}:
        return AliasPath('declaration', name)
    if name in {'effective_capabilities', 'capability_reasons'}:
        return AliasPath('policy', name)
    return name


class DomainSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, alias_generator=AliasGenerator(validation_alias=_source_alias))
    source_id: str
    display_name: str
    support: str
    aliases: list[str]
    effective_capabilities: list[str]
    capability_reasons: dict[str, str]


class DiscoverDomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hostname: str
    display_name: str
    sources: list[DomainSourceResponse]


class DiscoverDomainsResponse(BaseModel):
    items: list[DiscoverDomainResponse]
    next_cursor: str | None
    exhaustive: bool
    supports_url_resolution_outside_catalog: bool = True


@router.get('/discover/domains', response_model=DiscoverDomainsResponse)
def domains(query: str = Query(default='', max_length=200), cursor: str | None = None,
            limit: int = Query(default=30, ge=1, le=100)):
    manifests = {m.source_id: m for m in discovery.refresh_catalogues()}
    scope = {'purpose': 'domain-discovery', 'query': query.casefold(), 'limit': limit}
    offset = 0
    if cursor:
        try:
            value = json.loads(secrets.open_payload(cursor))
            if value.get('scope') != scope:
                raise ValueError('Domain filters changed; start again')
            offset = int(value['offset'])
            if not 0 <= offset <= 100000:
                raise ValueError('Invalid Domain continuation')
        except Exception as exc:
            raise HTTPException(422, 'Domain continuation expired or filters changed; start again') from exc
    with get_session() as session:
        query_statement = select(Domain).order_by(Domain.display_name, Domain.hostname)
        # Alias matching stays data-driven; the core contains no provider names.
        domains = list(session.scalars(query_statement))
        support = list(session.scalars(select(SourceDomain)))
        grouped = defaultdict(list)
        for row in support:
            grouped[row.domain_id].append(row)
        needle = query.casefold().strip()
        domains = [domain for domain in domains if not needle or needle in f'{domain.hostname} {domain.display_name}'.casefold()
            or any(needle in alias for row in grouped[domain.id] for alias in row.aliases or [])]
        page = domains[offset:offset + limit]
        views = []
        for domain in page:
            sources = [DomainSourceResponse.model_validate(DomainSourceView(row,
                effective(session, row.source_id, domain.hostname, manifest=manifests.get(row.source_id)),
                manifests[row.source_id].display_name if row.source_id in manifests else row.source_id))
                for row in grouped[domain.id]]
            views.append(DiscoverDomainResponse(id=domain.id, hostname=domain.hostname,
                display_name=domain.display_name, sources=sources))
        next_cursor = secrets.seal_payload(json.dumps({'scope': scope, 'offset': offset + limit}).encode()) if offset + limit < len(domains) else None
    return DiscoverDomainsResponse(items=views, next_cursor=next_cursor,
        exhaustive=bool(manifests) and all(m.exhaustive_domain_catalogue for m in manifests.values()))


class BrowseInput(SourceBrowseRequest):
    connection_id: int | None = Field(default=None, gt=0)


@router.post('/sources/{source_id}/browse', response_model=SourceBrowsePage)
def source_browse(source_id: str, data: BrowseInput, request: Request):
    require_connection(request, data.connection_id)
    try:
        return discovery.browse(source_id, SourceBrowseRequest.model_validate(data.model_dump(exclude={'connection_id'})),
            connection_id=data.connection_id)
    except (ValueError, RuntimeError) as exc:
        return _failure(exc)


@router.get('/sources/{source_id}/capabilities')
def source_capabilities(source_id: str, request: Request, domain: str,
                        connection_id: int | None = None):
    require_connection(request, connection_id)
    try:
        with get_session() as session:
            hostname = discovery.canonical_domain(session, source_id, domain)
            return effective(session, source_id, hostname, connection_id)
    except (ValueError, RuntimeError) as exc:
        return _failure(exc)


class InspectInput(BaseModel):
    reference: SourceMediaReference
    connection_id: int | None = Field(default=None, gt=0)


@router.post('/sources/{source_id}/media', response_model=NormalizedSnapshot)
def inspect_media(source_id: str, data: InspectInput, request: Request):
    require_connection(request, data.connection_id)
    try:
        with get_session() as session:
            options = source_options(session, source_id, data.connection_id)
        snapshot = SourceGateway().inspect(source_id, data.reference, **options)
        with get_session() as session:
            policy = effective(session, source_id, snapshot.reference.domain, data.connection_id, snapshot.capabilities)
        return snapshot.model_copy(update={'capabilities': set(policy.effective_capabilities)})
    except (ValueError, RuntimeError) as exc:
        return _failure(exc)


class ResolveInput(BaseModel):
    url: str = Field(min_length=8, max_length=8192)
    connection_id: int | None = Field(default=None, gt=0)


@router.post('/sources/{source_id}/resolve', response_model=NormalizedSnapshot)
def source_resolve(source_id: str, data: ResolveInput, request: Request):
    from backend.api.endpoints.vodloft.router import ResolveRequest, resolve
    return resolve(ResolveRequest(url=data.url, source_id=source_id, connection_id=data.connection_id), request)


def _stored_reference(session, source_id: str, reference_id: int, kind: str, request: Request):
    from backend.db.models.vodloft import MediaItem
    reference = session.get(SourceReference, reference_id)
    item = session.get(MediaItem, reference.item_id) if reference else None
    if not reference or not item or reference.source_id != source_id or item.kind != kind:
        raise HTTPException(404, 'Source media reference not found')
    require_connection(request, reference.connection_id)
    return SourceMediaReference(source_id=reference.source_id, domain=session.get(Domain, reference.domain_id).hostname,
        namespace=reference.namespace, upstream_id=reference.upstream_id, url=reference.url), reference.connection_id


@router.get('/sources/{source_id}/media/collections/{reference_id}/entries')
def stored_entries(source_id: str, reference_id: int, request: Request, cursor: str | None = None,
                   limit: int = Query(default=50, ge=1, le=100)):
    with get_session() as session:
        reference, connection_id = _stored_reference(session, source_id, reference_id, 'collection', request)
    try:
        return discovery.entries(source_id, reference.url, connection_id=connection_id, cursor=cursor, limit=limit)
    except (ValueError, RuntimeError) as exc:
        return _failure(exc)


@router.get('/sources/{source_id}/media/{kind}/{reference_id}', response_model=NormalizedSnapshot)
def stored_media(source_id: str, kind: str, reference_id: int, request: Request):
    with get_session() as session:
        reference, connection_id = _stored_reference(session, source_id, reference_id, kind, request)
    return inspect_media(source_id, InspectInput(reference=reference, connection_id=connection_id), request)


@router.post('/sources/connections/{connection_id}/capabilities', response_model=SourceConnectionStatus)
def check_connection_capabilities(connection_id: int, request: Request):
    require_connection(request, connection_id)
    if not principal(request).manages_library:
        raise HTTPException(403, 'A library manager must verify Source connections')
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        if not connection or not connection.enabled:
            raise HTTPException(404, 'Source connection not found')
        source_id = connection.source_id
        manifest = manifest_for(source_id)
        if not manifest or 'connection_capabilities' not in manifest.capabilities:
            return _failure(SourceInvocationError('unsupported_operation', 'Source does not advertise connection verification'))
        options = source_options(session, source_id, connection_id)
    try:
        result = SourceGateway().connection_status(source_id, **options)
    except (ValueError, RuntimeError) as exc:
        return _failure(exc)
    with get_session() as session:
        connection = session.get(SourceConnection, connection_id)
        connection.capabilities = sorted(result.capabilities) if result.capabilities is not None else None
        connection.domain_capabilities = {domain: sorted(capabilities) for domain, capabilities in result.domain_capabilities.items()}
        connection.authenticated = result.authenticated
        connection.last_capability_check_at = datetime.now(timezone.utc)
        session.commit()
    return result


def _job_reference(session, source_id: str, job_id: int, request: Request):
    job = session.get(AcquisitionJob, job_id)
    reference = session.get(SourceReference, job.reference_id) if job else None
    if not reference or reference.source_id != source_id:
        raise HTTPException(404, 'Source download not found')
    require_connection(request, reference.connection_id)
    return reference


class SourceItemInput(BaseModel):
    item_id: int = Field(gt=0)
    reference_id: int = Field(gt=0)


class SourceDownloadInput(SourceItemInput):
    profile_id: int | None = Field(default=None, gt=0)


@router.post('/sources/{source_id}/downloads', status_code=202)
def source_download(source_id: str, data: SourceDownloadInput, request: Request, background: BackgroundTasks):
    from backend.api.endpoints.vodloft.router import DownloadRequest, download_item
    with get_session() as session:
        reference = session.get(SourceReference, data.reference_id)
        if not reference or reference.source_id != source_id or reference.item_id != data.item_id:
            raise HTTPException(422, 'Source, item, and reference must match')
        require_connection(request, reference.connection_id)
    return download_item(data.item_id, background, DownloadRequest(profile_id=data.profile_id, reference_id=data.reference_id))


@router.get('/sources/{source_id}/downloads/{job_id}')
@router.get('/sources/{source_id}/downloads/{job_id}/progress')
def source_download_status(source_id: str, job_id: int, request: Request):
    from backend.api.endpoints.vodloft.router import job_status
    with get_session() as session:
        _job_reference(session, source_id, job_id, request)
    return job_status(job_id, request)


@router.post('/sources/{source_id}/downloads/{job_id}/cancel')
def source_download_cancel(source_id: str, job_id: int, request: Request):
    from backend.api.endpoints.vodloft.router import cancel_job
    with get_session() as session:
        _job_reference(session, source_id, job_id, request)
    return cancel_job(job_id)


@router.post('/sources/{source_id}/streams/resolve')
def source_stream(source_id: str, data: SourceItemInput, request: Request):
    from backend.api.endpoints.vodloft.playback import watch
    with get_session() as session:
        reference = session.get(SourceReference, data.reference_id)
        if not reference or reference.source_id != source_id or reference.item_id != data.item_id:
            raise HTTPException(422, 'Source, item, and reference must match')
        require_connection(request, reference.connection_id)
    # Only the opaque VodLoft playback session reaches the client, never a lease.
    return watch(data.item_id, request, reference_id=data.reference_id)
