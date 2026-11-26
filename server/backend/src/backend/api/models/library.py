from backend.api.models.base import RequestBase, ResponseBase
from backend.types.collection_types import LibraryCollectionSort


class LibraryCountsRead(ResponseBase):
    """How many collections, movies and videos the library holds."""

    collections: int
    movies: int
    videos: int


class LibraryPreferences(RequestBase):
    """How the user lists Collections: in the Library, and on a creator's page. What is left out stays as it was."""

    collection_sort: LibraryCollectionSort | None = None
    collection_sort_reversed: bool | None = None
    creator_collection_sort: LibraryCollectionSort | None = None
    creator_collection_sort_reversed: bool | None = None


class LibraryPreferencesRead(ResponseBase):
    """How the user lists Collections in the Library and on creator pages; without user accounts, VODLoft keeps none."""

    collection_sort: LibraryCollectionSort = LibraryCollectionSort.RECENTLY_USED
    collection_sort_reversed: bool = False
    creator_collection_sort: LibraryCollectionSort = LibraryCollectionSort.RECENTLY_USED
    creator_collection_sort_reversed: bool = False
    saved: bool
    """Whether VODLoft keeps the choice for this user; without user accounts the browser keeps it."""
