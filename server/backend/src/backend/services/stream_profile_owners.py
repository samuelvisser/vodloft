"""Who may see and change a Stream Profile: its owner, and those who manage every one."""
from __future__ import annotations

from fastapi import HTTPException

from backend.security.access import Access, Area, Level


def sees_every_profile(access: Access) -> bool:
    return access.allows(Area.STREAM_PROFILES, Level.MANAGE)


def owned_by(query, owner_column, access: Access):
    """``query`` limited to the user's own profiles, unless they manage every one."""
    if sees_every_profile(access):
        return query
    return query.filter(owner_column == access.user_id)


def check_owner(item, access: Access) -> None:
    """Someone else's profile is answered as not found, so its existence does not leak."""
    if not sees_every_profile(access) and item.owner_user_id != access.user_id:
        raise HTTPException(status_code=404, detail="Stream profile not found")
