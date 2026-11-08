from backend.api.models.base import ResponseBase


class LibraryCountsRead(ResponseBase):
    """How many collections, movies and videos the library holds."""

    collections: int
    movies: int
    videos: int
