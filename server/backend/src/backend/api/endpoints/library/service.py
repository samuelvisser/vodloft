from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.library import LibraryCountsRead, LibraryPreferences, LibraryPreferencesRead
from backend.db.models import Collection, Movie, User, Video
from backend.security.access import Access


def get_library_counts(s: Session) -> LibraryCountsRead:
    """Counted without loading the items, so the library can show its tabs before their lists arrive."""
    return LibraryCountsRead(
        collections=s.scalar(select(func.count()).select_from(Collection)),
        movies=s.scalar(select(func.count()).select_from(Movie)),
        videos=s.scalar(select(func.count()).select_from(Video)),
    )


class LibraryPreferencesNeedAnAccount(Exception):
    """The Library's order is kept per user account."""


def get_library_preferences(s: Session, access: Access) -> LibraryPreferencesRead:
    """How this user lists the Library; the default order without an account or a choice of their own."""
    user = s.get(User, access.user_id) if access.user_id is not None else None
    if user is None:
        return LibraryPreferencesRead(saved=False)
    return LibraryPreferencesRead(
        collection_sort=user.library_collection_sort,
        collection_sort_reversed=user.library_collection_sort_reversed,
        saved=True,
    )


def save_library_preferences(s: Session, access: Access, preferences: LibraryPreferences) -> LibraryPreferencesRead:
    user = s.get(User, access.user_id) if access.user_id is not None else None
    if user is None:
        raise LibraryPreferencesNeedAnAccount("Without user accounts, the browser remembers how you list the Library.")
    user.library_collection_sort = preferences.collection_sort
    user.library_collection_sort_reversed = preferences.collection_sort_reversed
    s.flush()
    return get_library_preferences(s, access)
