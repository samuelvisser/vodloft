"""Collection membership policy shared by scheduling and consumption."""
from backend.db.models.vodloft import CollectionEntry, SourceReference
from sqlalchemy import or_, select


def source_memberships(session, collection_id: int, source_id: str | None = None,
                       connection_id: int | None = None) -> list[CollectionEntry]:
    query = select(CollectionEntry).where(CollectionEntry.collection_id == collection_id, CollectionEntry.active.is_(True))
    if source_id is not None:
        # Locally managed membership may have no upstream Source provenance.
        query = query.where(or_(CollectionEntry.source_id.is_(None),
            (CollectionEntry.source_id == source_id) & (CollectionEntry.connection_key == (connection_id or 0))))
    return list(session.scalars(query.order_by(CollectionEntry.position)).all())


def known_groups(session, collection_id: int, reference_id: int | None = None) -> list[str]:
    reference = session.get(SourceReference, reference_id) if reference_id is not None else None
    return list(dict.fromkeys(entry.group or "" for entry in source_memberships(
        session, collection_id, reference.source_id if reference else None, reference.connection_id if reference else None)))


def matches_membership(entry, policy, *, session=None) -> bool:
    if entry.active is False:
        return False
    if session is not None and policy.source_reference_id is not None:
        reference = session.get(SourceReference, policy.source_reference_id)
        if not reference or entry.source_id is not None and (entry.source_id != reference.source_id or
                entry.connection_key != (reference.connection_id or 0)):
            return False
    group = entry.group or ""
    if policy.selected_groups is not None and group not in policy.selected_groups:
        if not policy.include_future_groups or group in policy.known_groups:
            return False
    return policy.member_roles is None or (entry.role or "") in policy.member_roles
