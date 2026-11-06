from __future__ import annotations

from typing import Literal, Union

from pydantic import Field

from backend.api.models.local_media_profile import (
    LocalMediaProfileAPIBaseOut,
)
from backend.api.models.base import RequestBase
from backend.api.models.custom_metadata import IndexingValueDefinitionAPI
from backend.services.local_media_profile_inputs import CollectionLocalMediaProfileInput, NewCollectionLocalMediaProfile
from backend.types.local_media_profile_types import (
    LocalMediaProfileType,
    CollectionLocalMediaProfileScope,
)


class CollectionLocalMediaProfileAPICreate(RequestBase, NewCollectionLocalMediaProfile):
    """Create a Collection Local Media Profile."""


class CollectionLocalMediaProfileAPIUpdate(RequestBase, CollectionLocalMediaProfileInput):
    """Update a Collection Local Media Profile."""


class CollectionLocalMediaProfileAPIRead(LocalMediaProfileAPIBaseOut):
    """Read a Collection Local Media Profile."""

    type: Literal["collection"] = LocalMediaProfileType.COLLECTION.value
    collection_scope: Union[CollectionLocalMediaProfileScope, str] = CollectionLocalMediaProfileScope.BOTH
    download_collection_assets: bool | None = None
    indexing_values: list[IndexingValueDefinitionAPI] = Field(default_factory=list)
