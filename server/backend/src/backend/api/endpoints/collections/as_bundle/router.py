from fastapi import APIRouter, HTTPException, Request, status

from .service import *
from ....models.collection import CollectionAPIRead
from ....models.collection_as_bundle import CollectionAPICreateBundle
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in

router = APIRouter(prefix = "/as-bundle")


@router.post("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionAPIRead, status_code=status.HTTP_201_CREATED)
def collection_create_as_bundle(body: CollectionAPICreateBundle, request: Request, access: Access = signed_in()):
    """
    Create a new show, optionally with media, download, and stream profiles in a single operation.
    """
    access.check_link_at(body.collection.source_key, body.collection.sharing_url)
    if body.stream_profile is not None and not access.allows(Area.STREAM_PROFILES):
        raise HTTPException(status_code=403, detail="You may not create Stream Profiles.")
    with db_session() as s:
        try:
            result = create_collection_bundle(s, request, body, added_by_id=access.user_id)
            s.commit()
            return result
        except Exception:
            s.rollback()
            raise
