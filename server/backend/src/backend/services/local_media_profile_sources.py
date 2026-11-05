"""Which Sources a Local Media Profile is offered for, and what it can download for them."""
from __future__ import annotations

from sources import DownloadOptions, Feature, Site, Source, all_sources

from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, LocalMediaProfileType, PreferredFormat

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


def profile_download_options(profile_type: LocalMediaProfileType | str, source_keys: list[str] | None) -> DownloadOptions:
    """What a profile can download: everything one of the Sources it is offered for can."""
    return DownloadOptions.combined(
        source.download_options for source in sources_for_profile_type(profile_type)
        if profile_offered_for_source(source_keys, source.id)
    )


def offers_format(options: DownloadOptions, preferred_format: PreferredFormat | str) -> bool:
    preferred_format = PreferredFormat(preferred_format)
    if preferred_format == PreferredFormat.FORMAT_HLS:
        return options.hls_bundle
    if preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY:
        return options.audio_only
    return PREFERRED_FORMAT_HEIGHTS[preferred_format] in options.video_heights


def format_for_site(site: Site, preferred_format: str) -> str:
    """What a profile downloads from one Site: its own choice where the Site offers it, otherwise the
    nearest video. A profile offered for several Sources can choose what only some of them have, such
    as The Daily Wire's HLS bundle, whose highest resolution is 1080p."""
    options = site.downloads
    if preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value or offers_format(options, preferred_format):
        return preferred_format
    wanted = 1080 if preferred_format == PreferredFormat.FORMAT_HLS.value else PREFERRED_FORMAT_HEIGHTS[PreferredFormat(preferred_format)]
    fitting = [height for height in options.video_heights if height <= wanted]
    height = max(fitting) if fitting else min(options.video_heights)
    return next(fmt.value for fmt, value in PREFERRED_FORMAT_HEIGHTS.items() if value == height)
