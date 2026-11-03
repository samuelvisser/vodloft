"""Which Sources a Local Media Profile is offered for."""
from __future__ import annotations

from sources import Feature, Source, all_sources

from backend.types.local_media_profile_types import LocalMediaProfileType

# The Feature a Source needs before a profile of each type can store its media.
_PROFILE_TYPE_FEATURES = {
    LocalMediaProfileType.COLLECTION: Feature.COLLECTIONS,
    LocalMediaProfileType.MOVIE: Feature.MOVIES,
    LocalMediaProfileType.VIDEO: Feature.VIDEOS,
}


def sources_for_profile_type(profile_type: LocalMediaProfileType | str) -> list[Source]:
    """Every Source whose media a Local Media Profile of this type can store."""
    feature = _PROFILE_TYPE_FEATURES[LocalMediaProfileType(profile_type)]
    return [source for source in all_sources() if source.has(feature)]


def profile_offered_for_source(source_keys: list[str] | None, source_key: str) -> bool:
    """A profile without a list of Sources is offered for every Source."""
    return source_keys is None or source_key in source_keys
