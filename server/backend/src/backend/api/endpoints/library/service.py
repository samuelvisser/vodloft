from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.library import LibraryCountsRead
from backend.db.models import Collection, Movie, Video


def get_library_counts(s: Session) -> LibraryCountsRead:
    """Counted without loading the items, so the library can show its tabs before their lists arrive."""
    return LibraryCountsRead(
        collections=s.scalar(select(func.count()).select_from(Collection)),
        movies=s.scalar(select(func.count()).select_from(Movie)),
        videos=s.scalar(select(func.count()).select_from(Video)),
    )
