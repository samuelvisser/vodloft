from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.core import run_write_transaction
from backend.services.movies import sync_dailywire_movie_metadata, sync_movie_extras
from backend.db.models import Movie
from sources.dailywire.api.dw_api.movie import MovieMiddlewareClient
from sources.dailywire.auth import DeviceAuthClient


async def run_refresh_movie_extras(
    session: Session,
    *,
    movie_id: int,
    progress=None,
) -> int:
    movie = session.get(Movie, movie_id)
    if movie is None:
        raise ValueError(f"Movie {movie_id} was deleted before its extras could be refreshed")
    movie_title, movie_slug = movie.title, movie.slug
    session.rollback()

    if progress is not None:
        progress.set(10, f"Fetching metadata for '{movie_title}'")

    tokens = DeviceAuthClient().get_token()
    client = MovieMiddlewareClient(access_token=tokens.access_token if tokens else None)
    movie_data = client.get_movie_page(movie_slug)

    if progress is not None:
        progress.set(65, f"Indexing {len(movie_data.movie_extras)} movie extra(s)")

    # The canonical movie page contains both the parent movie metadata and extras,
    # so one refresh captures status/release changes and newly published extras.
    def store(w: Session) -> int:
        stored = w.get(Movie, movie_id)
        if stored is None:
            raise ValueError(f"Movie '{movie_title}' was deleted before its extras could be refreshed")
        sync_dailywire_movie_metadata(w, movie=stored, movie_data=movie_data)
        return sync_movie_extras(
            w,
            movie=stored,
            extras=movie_data.movie_extras,
            official_trailer=movie_data.trailer,
        )

    added = run_write_transaction(store)

    if progress is not None:
        progress.set(100, f"Added {added} new movie extra(s)")
    return added
