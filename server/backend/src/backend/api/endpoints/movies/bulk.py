"""Bulk edit in the Library: deleting many movies at once."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.api.models.profile_bulk import BulkResultRead, BulkSelectionIn
from backend.db.models.media_item import Movie

from .service import delete_movie


def delete_movies(s: Session, body: BulkSelectionIn) -> BulkResultRead:
    movies = s.query(Movie).filter(Movie.id.in_(body.ids)).all()
    for movie in movies:
        delete_movie(s, movie.slug)
    return BulkResultRead(done=len(movies), skipped=[])
