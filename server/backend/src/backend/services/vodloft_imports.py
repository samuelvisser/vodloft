"""Canonical identity and normalized snapshot import shared by API and workers."""
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select, update
from source_contracts import MediaSnapshot, SourceMediaReference
from backend.db import get_session
from backend.db.models.vodloft import (Domain, SourceDomain, SourceReference, SourceSnapshot,
    MediaItem, CollectionEntry, CollectionScan, MovieExtraParent)
from backend.source_manager.runtime import command_for

_MISSING = object()


class LibraryImportError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def domain_for(session, hostname: str) -> Domain:
    hostname = hostname.rstrip(".").lower().encode("idna").decode("ascii")
    domain = session.scalar(select(Domain).where(Domain.hostname == hostname))
    if not domain:
        domain = Domain(hostname=hostname, display_name=hostname)
        session.add(domain)
        session.flush()
    return domain



def upsert(session, reference: SourceMediaReference, kind: str, title: str,
            description=_MISSING, duration=_MISSING,
            artwork_url=_MISSING, connection_id: int | None = None,
            published_at=_MISSING, capabilities=_MISSING,
            is_live=_MISSING, formats=_MISSING, normalized_metadata: dict | None = None,
            existing_item_id: int | None = None) -> MediaItem:
    domain = domain_for(session, reference.domain)
    supported = session.scalar(select(SourceDomain).where(
        SourceDomain.source_id == reference.source_id, SourceDomain.domain_id == domain.id))
    if not supported:
        session.add(SourceDomain(source_id=reference.source_id, domain_id=domain.id, support="verified"))
        session.flush()
    source = session.scalar(select(SourceReference).where(
        SourceReference.source_id == reference.source_id,
        SourceReference.domain_id == domain.id,
        SourceReference.namespace == reference.namespace,
        SourceReference.upstream_id == reference.upstream_id,
        SourceReference.connection_key == (connection_id or 0),
    ))
    reference_capabilities = sorted(capabilities) if capabilities is not _MISSING and capabilities is not None else None
    reference_formats = [format.model_dump(mode="json") for format in formats] if formats is not _MISSING else None
    if source:
        if capabilities is not _MISSING:
            source.capabilities = reference_capabilities
        if formats is not _MISSING:
            source.formats = reference_formats
    if existing_item_id is not None:
        item = session.get(MediaItem, existing_item_id)
        if not item:
            raise LibraryImportError(404, "The existing library item was not found")
        effective_kind = item.user_kind or item.kind
        if item.domain_id != domain.id:
            raise LibraryImportError(422, "Link a reference from the same content Domain")
        if effective_kind != kind and not (kind == "video" and effective_kind in {"movie", "movie_extra"}):
            raise LibraryImportError(422, "The reference and existing item have incompatible media types")
        # Confirmation may add a new reference, but must never move an identity
        # already used by another canonical item, account, job, or artifact.
        related = session.scalars(select(SourceReference).where(
            SourceReference.source_id == reference.source_id,
            SourceReference.domain_id == domain.id,
            or_((SourceReference.namespace == reference.namespace) &
                (SourceReference.upstream_id == reference.upstream_id),
                SourceReference.url == reference.url))).all()
        if any(candidate.item_id != item.id for candidate in related):
            raise LibraryImportError(409, "This Source reference already belongs to another library item")
        if source:
            source.url = reference.url
        else:
            session.add(SourceReference(item_id=item.id, domain_id=domain.id,
                source_id=reference.source_id, namespace=reference.namespace,
                upstream_id=reference.upstream_id, url=reference.url,
                connection_id=connection_id, connection_key=connection_id or 0,
                capabilities=reference_capabilities, formats=reference_formats))
        # Attaching an acquisition Source does not replace the chosen metadata.
        # Its verified snapshot is recorded separately by the import operation.
        return item
    if source:
        item = session.get(MediaItem, source.item_id)
        item.title = title
        if description is not _MISSING:
            item.description = description
        if duration is not _MISSING:
            item.duration = duration
        if artwork_url is not _MISSING:
            item.artwork_url = artwork_url
        if published_at is not _MISSING:
            item.published_at = published_at
        if capabilities is not _MISSING:
            item.capabilities = sorted(capabilities) if capabilities is not None else None
        if is_live is not _MISSING:
            item.is_live = is_live
        if formats is not _MISSING:
            item.formats = [format.model_dump(mode="json") for format in formats]
        source.url = reference.url
    else:
        related = session.scalar(select(SourceReference).where(
            SourceReference.source_id == reference.source_id,
            SourceReference.domain_id == domain.id,
            SourceReference.namespace == reference.namespace,
            SourceReference.upstream_id == reference.upstream_id))
        if not related:
            related = session.scalar(select(SourceReference).where(
                SourceReference.source_id == reference.source_id,
                SourceReference.domain_id == domain.id,
                SourceReference.url == reference.url))
        if related:
            item = session.get(MediaItem, related.item_id)
        else:
            item = MediaItem(domain_id=domain.id, kind=kind, title=title,
                             description=None if description is _MISSING else description,
                             duration=None if duration is _MISSING else duration,
                             artwork_url=None if artwork_url is _MISSING else artwork_url,
                             published_at=None if published_at is _MISSING else published_at,
                             capabilities=sorted(capabilities) if capabilities is not _MISSING and capabilities is not None else None,
                             is_live=None if is_live is _MISSING else is_live,
                             formats=[format.model_dump(mode="json") for format in formats] if formats is not _MISSING else None)
            session.add(item)
            session.flush()
        session.add(SourceReference(item_id=item.id, domain_id=domain.id,
            source_id=reference.source_id, namespace=reference.namespace,
            upstream_id=reference.upstream_id, url=reference.url,
            connection_id=connection_id, connection_key=connection_id or 0,
            capabilities=reference_capabilities, formats=reference_formats))
    if normalized_metadata is not None:
        item.normalized_metadata = {**(item.normalized_metadata or {}), **normalized_metadata}
    return item


def reconcile_members(session, collection_id: int, source_id: str, connection_id: int | None,
                      scan_key: str) -> int:
    """Only an authoritative, completed scan may retire upstream membership.

    Canonical media, files, demands and saved export decisions are never removed
    here. Another Source/account's members and local manual entries are untouched.
    """
    result = session.execute(update(CollectionEntry).where(
        CollectionEntry.collection_id == collection_id,
        CollectionEntry.source_id == source_id,
        CollectionEntry.connection_key == (connection_id or 0),
        CollectionEntry.active.is_(True),
        or_(CollectionEntry.last_seen_scan_key.is_(None),
            CollectionEntry.last_seen_scan_key != scan_key)).values(active=False))
    return result.rowcount


def store_snapshot(snapshot: MediaSnapshot, connection_id: int | None = None,
                   *, scan_error: str | None = None, next_cursor: str | None = None,
                   runtime_version: str | None = None, existing_item_id: int | None = None,
                   scan_key: str | None = None, reconcile: bool = True,
                   record_scan: bool = True, lease_scan_id: int | None = None,
                   lease_owner: str | None = None) -> int:
    scan_key = scan_key or str(uuid.uuid4())
    with get_session() as session:
        if lease_scan_id is not None:
            changed = session.execute(update(CollectionScan).where(
                CollectionScan.id == lease_scan_id, CollectionScan.lease_owner == lease_owner,
                CollectionScan.active_reference_id.is_not(None)).values(
                    lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=300)))
            if not changed.rowcount:
                raise LibraryImportError(409, "Collection scan no longer owns its lease")
        item = upsert(session, snapshot.reference, snapshot.kind, snapshot.title,
                       snapshot.description if "description" in snapshot.model_fields_set else _MISSING,
                       snapshot.duration if "duration" in snapshot.model_fields_set else _MISSING,
                       snapshot.artwork_url if "artwork_url" in snapshot.model_fields_set else _MISSING,
                       connection_id,
                       published_at=snapshot.published_at if "published_at" in snapshot.model_fields_set else _MISSING,
                       capabilities=snapshot.capabilities if "capabilities" in snapshot.model_fields_set else _MISSING,
                       is_live=snapshot.is_live if "is_live" in snapshot.model_fields_set else _MISSING,
                       formats=snapshot.formats if "formats" in snapshot.model_fields_set else _MISSING,
                       normalized_metadata=snapshot.model_dump(mode="json", include={
                           "artwork", "chapters", "tracks", "author", "movie_year"}, exclude_unset=True),
                       existing_item_id=existing_item_id)
        session.flush()
        if snapshot.kind == "collection" and record_scan and existing_item_id is None:
            active_scan = session.scalar(select(CollectionScan.id).where(
                CollectionScan.collection_id == item.id,
                CollectionScan.source_id == snapshot.reference.source_id,
                CollectionScan.connection_id == connection_id,
                CollectionScan.active_reference_id.is_not(None)))
            if active_scan:
                raise LibraryImportError(409, "This Collection has a pending refresh; resume it before reimporting")
        metadata_snapshot = snapshot.model_dump(mode="json", exclude={"reference", "entries", "extras"},
                                                exclude_unset=True)
        previous = session.scalar(select(SourceSnapshot).where(
            SourceSnapshot.item_id == item.id,
            SourceSnapshot.source_id == snapshot.reference.source_id,
            SourceSnapshot.connection_id == connection_id).order_by(SourceSnapshot.id.desc()))
        if not previous or previous.metadata_snapshot != metadata_snapshot:
            try:
                source_version = runtime_version or command_for(snapshot.reference.source_id)[1]
            except (ValueError, RuntimeError):
                source_version = "configured"
            session.add(SourceSnapshot(item_id=item.id, source_id=snapshot.reference.source_id,
                connection_id=connection_id, runtime_version=source_version,
                metadata_snapshot=metadata_snapshot))
        if snapshot.kind == "collection" and existing_item_id is None:
            for entry in snapshot.entries:
                child = upsert(session, entry.reference, entry.kind, entry.title,
                                connection_id=connection_id,
                                published_at=entry.published_at if "published_at" in entry.model_fields_set else _MISSING,
                                capabilities=entry.capabilities if "capabilities" in entry.model_fields_set else _MISSING,
                                is_live=entry.is_live if "is_live" in entry.model_fields_set else _MISSING)
                session.flush()
                if child.id == item.id:
                    continue
                identity = (CollectionEntry.occurrence_key == entry.occurrence_id
                            if entry.occurrence_id else
                            (CollectionEntry.item_id == child.id) & CollectionEntry.occurrence_key.is_(None))
                membership = session.scalar(select(CollectionEntry).where(
                    CollectionEntry.collection_id == item.id,
                    CollectionEntry.source_id == snapshot.reference.source_id,
                    CollectionEntry.connection_key == (connection_id or 0), identity))
                if membership:
                    membership.item_id = child.id
                    membership.position = entry.position
                    membership.active = True
                    membership.last_seen_scan_key = scan_key
                    for field in ("group", "episode_number", "role"):
                        if field in entry.model_fields_set:
                            setattr(membership, field, getattr(entry, field))
                else:
                    session.add(CollectionEntry(collection_id=item.id, item_id=child.id,
                        source_id=snapshot.reference.source_id, connection_id=connection_id,
                        connection_key=connection_id or 0, last_seen_scan_key=scan_key,
                        position=entry.position, group=entry.group,
                        episode_number=entry.episode_number, role=entry.role,
                        occurrence_key=entry.occurrence_id))
            removed = reconcile_members(session, item.id, snapshot.reference.source_id,
                connection_id, scan_key) if reconcile and snapshot.enumeration_complete else 0
            if record_scan:
                session.add(CollectionScan(collection_id=item.id, source_id=snapshot.reference.source_id,
                    scan_key=scan_key, complete=snapshot.enumeration_complete,
                    status="complete" if snapshot.enumeration_complete else "partial",
                    entry_count=len(snapshot.entries), removed_count=removed,
                    connection_id=connection_id, next_cursor=next_cursor,
                    runtime_version=runtime_version, error=scan_error))
        if snapshot.kind == "movie" and existing_item_id is None:
            for extra in snapshot.extras:
                child = upsert(session, extra.reference, "movie_extra", extra.title,
                                connection_id=connection_id,
                                capabilities=extra.capabilities if "capabilities" in extra.model_fields_set else _MISSING)
                if child.user_kind and child.user_kind != "movie_extra":
                    continue
                child.kind = "movie_extra"
                if child.user_parent_ids is None:
                    child.parent_id = child.parent_id or item.id
                if child.user_extra_type is None:
                    child.extra_type = extra.extra_type or "other"
                session.flush()
                membership = session.scalar(select(MovieExtraParent).where(
                    MovieExtraParent.movie_id == item.id, MovieExtraParent.extra_id == child.id))
                if child.user_parent_ids is None or item.id in child.user_parent_ids:
                    role = child.user_extra_type or extra.extra_type or "other"
                    if not membership:
                        session.add(MovieExtraParent(movie_id=item.id, extra_id=child.id, extra_type=role))
                    else:
                        membership.extra_type = role
        session.flush()
        imported_item_id = item.id
        session.commit()
    return imported_item_id
