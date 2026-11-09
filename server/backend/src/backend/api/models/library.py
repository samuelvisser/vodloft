from backend.api.models.base import RequestBase, ResponseBase
from backend.types.collection_types import LibraryCollectionSort


class LibraryCountsRead(ResponseBase):
    """How many collections, movies and videos the library holds."""

    collections: int
    movies: int
    videos: int


class LibraryPreferences(RequestBase):
    """How the user lists the Library's Collections."""

    collection_sort: LibraryCollectionSort
    collection_sort_reversed: bool = False


class LibraryPreferencesRead(ResponseBase):
    """How the user lists the Library's Collections; without user accounts, VODLoft keeps none."""

    collection_sort: LibraryCollectionSort = LibraryCollectionSort.OFTEN_USED
    collection_sort_reversed: bool = False
    saved: bool
    """Whether VODLoft keeps the choice for this user; without user accounts the browser keeps it."""
