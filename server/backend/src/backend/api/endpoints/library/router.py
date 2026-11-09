from fastapi import APIRouter, HTTPException

from backend.api.models.library import LibraryCountsRead, LibraryPreferences, LibraryPreferencesRead
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, signed_in

from .service import (
    LibraryPreferencesNeedAnAccount,
    get_library_counts,
    get_library_preferences,
    save_library_preferences,
)

router = APIRouter(prefix="/library", tags=["Library"])


@router.get("/counts", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=LibraryCountsRead)
def library_counts():
    with db_session() as s:
        return get_library_counts(s)


@router.get("/preferences", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=LibraryPreferencesRead)
def library_preferences(access: Access = signed_in()):
    """How the signed-in user lists the Library."""
    with db_session() as s:
        return get_library_preferences(s, access)


@router.put("/preferences", dependencies=[requires(Area.LIBRARY, Level.VIEW)], response_model=LibraryPreferencesRead)
def library_preferences_save(body: LibraryPreferences, access: Access = signed_in()):
    """Remember how the signed-in user lists the Library."""
    def work(s):
        try:
            return save_library_preferences(s, access, body)
        except LibraryPreferencesNeedAnAccount as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return run_write_transaction(work, concurrent=True)
