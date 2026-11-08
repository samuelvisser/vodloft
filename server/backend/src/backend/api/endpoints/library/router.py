from fastapi import APIRouter

from backend.api.models.library import LibraryCountsRead
from backend.app import db_session
from backend.security.access import Area, Level
from backend.security.deps import requires

from .service import get_library_counts

router = APIRouter(prefix="/library", tags=["Library"])


@router.get("/counts", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=LibraryCountsRead)
def library_counts():
    with db_session() as s:
        return get_library_counts(s)
