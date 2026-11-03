from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.db.models import LocalMediaProfileBase
from backend.services.local_media_profile_sources import profile_offered_for_source
from backend.types.local_media_profile_types import LocalMediaProfileType


def require_local_media_profile_type(
    session: Session,
    profile_id: int,
    expected_type: LocalMediaProfileType,
    source_key: str | None = None,
) -> LocalMediaProfileBase:
    profile = session.get(LocalMediaProfileBase, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Local media profile not found")
    if profile.type != expected_type.value:
        label = expected_type.value.title()
        raise HTTPException(
            status_code=422,
            detail=f"This operation requires a {label} Local Media Profile",
        )
    if source_key is not None and not profile_offered_for_source(profile.source_keys, source_key):
        raise HTTPException(status_code=422, detail=f"Local Media Profile '{profile.name}' is not available for this Source")
    return profile
