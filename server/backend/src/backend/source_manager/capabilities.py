"""Effective operation policy: Source -> Domain -> connection -> media reference."""
from dataclasses import dataclass, field
import threading
import time

from sqlalchemy import select
from source_contracts import SourceManifest

from backend.db.models.vodloft import Domain, SourceConnection, SourceDomain, SourceReference
from backend.source_manager.gateway import SourceGateway

_cache: dict[tuple, tuple[float, SourceManifest | None]] = {}
_lock = threading.Lock()
OPERATIONS = {'resolve_url', 'inspect_media', 'enumerate_collection', 'download', 'stream_lease', 'search', 'browse'}


@dataclass(frozen=True)
class EffectiveCapabilities:
    effective_capabilities: list[str]
    capability_reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceCapabilities:
    reference: SourceReference
    effective_capabilities: list[str]
    capability_reasons: dict[str, str]


def manifest_for(source_id: str, gateway: SourceGateway | None = None) -> SourceManifest | None:
    gateway = gateway or SourceGateway()
    command = gateway.commands.get(source_id)
    if not command:
        return None
    key = (source_id, tuple(command))
    with _lock:
        cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    manifest = next(iter(SourceGateway({source_id: command}).manifests()), None)
    with _lock:
        if len(_cache) >= 128:
            _cache.clear()
        _cache[key] = time.monotonic(), manifest
    return manifest


def effective(session, source_id: str, hostname: str | None, connection_id: int | None = None,
              item_capabilities: list[str] | set[str] | None = None,
              *, manifest: SourceManifest | None = None) -> EffectiveCapabilities:
    manifest = manifest or manifest_for(source_id)
    allowed, reasons = set(manifest.capabilities) & OPERATIONS if manifest else set(), {}
    for operation in OPERATIONS - allowed:
        reasons[operation] = 'Source runtime is unavailable' if manifest is None else 'Source does not advertise this operation'
    domain = session.scalar(select(Domain).where(Domain.hostname == hostname))
    support = session.scalar(select(SourceDomain).where(SourceDomain.domain_id == domain.id,
        SourceDomain.source_id == source_id)) if domain else None
    connection = session.get(SourceConnection, connection_id) if connection_id is not None else None

    def restrict(capabilities, reason):
        nonlocal allowed
        excluded = allowed - set(capabilities)
        for operation in excluded:
            reasons[operation] = reason
        allowed -= excluded

    if support:
        if support.support == 'failing':
            restrict(set(), 'This Source currently reports failing support for the Domain')
        elif support.support == 'authentication_required' and (connection is None or connection.authenticated is False):
            restrict({'resolve_url', 'inspect_media'}, 'Choose an authorized Source connection for this Domain')
        if support.capabilities is not None:
            restrict(support.capabilities, 'Source does not advertise this operation on this Domain')
    if connection_id is not None:
        if connection is None or not connection.enabled or connection.source_id != source_id:
            restrict(set(), 'The selected Source connection is disabled or unavailable')
        else:
            if connection.capabilities is not None:
                restrict(connection.capabilities, 'The selected Source connection does not permit this operation')
            scoped = (connection.domain_capabilities or {}).get(hostname)
            if scoped is not None:
                restrict(scoped, 'The selected Source connection does not permit this operation on this Domain')
    if item_capabilities is not None:
        restrict(item_capabilities, 'The selected Source/account does not advertise this operation for this item')
    return EffectiveCapabilities(sorted(allowed), reasons)


def reference_capabilities(session, reference: SourceReference) -> ReferenceCapabilities:
    hostname = session.get(Domain, reference.domain_id).hostname
    policy = effective(session, reference.source_id, hostname, reference.connection_id, reference.capabilities)
    return ReferenceCapabilities(reference, policy.effective_capabilities, policy.capability_reasons)
