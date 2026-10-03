"""Collection membership policy shared by scheduling and consumption."""
from backend.db.models.vodloft import CollectionEntry
from sqlalchemy import select


def known_groups(session, collection_id: int) -> list[str]:
    return list(dict.fromkeys(group or "" for group in session.scalars(select(
        CollectionEntry.group).where(CollectionEntry.collection_id == collection_id)).all()))


def matches_membership(entry, policy) -> bool:
    group = entry.group or ""
    if policy.selected_groups is not None and group not in policy.selected_groups:
        if not policy.include_future_groups or group in policy.known_groups:
            return False
    return policy.member_roles is None or (entry.role or "") in policy.member_roles
