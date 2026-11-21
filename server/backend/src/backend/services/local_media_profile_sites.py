"""Which Sites a Local Media Profile is offered for, and what it can download from them.

A profile lists the Sites it is offered for, such as YouTube or The Daily Wire. A profile that includes upcoming
Sites also takes every Site VODLoft sees for the first time: the Site joins its list, so the user can still take
it out again later. A new profile starts with every Site VODLoft knows.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from config.settings.site_settings import SiteSettingGroup
from sources import ANY_DOMAIN, DownloadOptions, Feature, Site, SiteSetting, Source, all_sources, site_of

from backend.types.local_media_profile_types import PREFERRED_FORMAT_HEIGHTS, LocalMediaProfileType, PreferredFormat

# The Features of which a Source needs one before a profile of each type can store its media. A Video profile
# keeps single videos, and movies with their extras.
_PROFILE_TYPE_FEATURES = {
    LocalMediaProfileType.COLLECTION: (Feature.COLLECTIONS,),
    LocalMediaProfileType.VIDEO: (Feature.VIDEOS, Feature.MOVIES),
}


def _stores_type(source: Source, profile_type: LocalMediaProfileType | str) -> bool:
    return any(source.has(feature) for feature in _PROFILE_TYPE_FEATURES[LocalMediaProfileType(profile_type)])


def _fetching_sources(site_key: str) -> list[Source]:
    """The Sources that fetch the Site: the ones made for it, and the ones that fetch any site."""
    return [source for source in all_sources() if ANY_DOMAIN in source.domains or source.site_of(site_key) is not None]


def site_offered_for_type(profile_type: LocalMediaProfileType | str, site_key: str) -> bool:
    """Whether a profile of this type can store media from the Site, such as collections from YouTube."""
    return any(_stores_type(source, profile_type) for source in _fetching_sources(site_key))


def takes_upcoming_sites(profile_type: LocalMediaProfileType | str) -> bool:
    """Whether a profile of this type can get media from Sites VODLoft has not seen yet: only a Source that
    fetches any site brings new ones."""
    return any(ANY_DOMAIN in source.domains and _stores_type(source, profile_type) for source in all_sources())


def _upcoming_sites(profile_type: LocalMediaProfileType | str | None = None) -> list[Site]:
    """What a Site VODLoft has not seen yet is like: what each Source that fetches any site makes of a Site it
    has no contract of its own for."""
    return [
        site for source in all_sources()
        if ANY_DOMAIN in source.domains and (profile_type is None or _stores_type(source, profile_type))
        and (site := source.site_of(_UNSEEN_SITE)) is not None
    ]


def _upcoming_downloads(profile_type: LocalMediaProfileType | str | None = None) -> DownloadOptions:
    """What a Site VODLoft has not seen yet can download."""
    return DownloadOptions.combined(site.downloads for site in _upcoming_sites(profile_type))


# A key no Site has, for what a Site that is still to come offers.
_UNSEEN_SITE = "generic:upcoming.invalid"


def known_sites(s: Session) -> list[Site]:
    """Every Site VODLoft knows, by name."""
    from backend.db.models import Site as SiteRecord

    return sorted(
        (Site(key, name) for key, name in s.execute(select(SiteRecord.key, SiteRecord.name)).all()),
        key=lambda site: site.name.lower(),
    )


def known_site_keys(connection: Connection | Session) -> set[str]:
    from backend.db.models import Site as SiteRecord

    return set(connection.execute(select(SiteRecord.key)).scalars())


def every_known_site(connection: Connection | Session, profile_type: LocalMediaProfileType | str) -> list[str]:
    """The Sites a new profile of this type starts with: every Site VODLoft knows that it can store media from."""
    return sorted(key for key in known_site_keys(connection) if site_offered_for_type(profile_type, key))


def movie_site_keys(connection: Connection | Session) -> list[str]:
    """The Sites VODLoft knows that have movies, such as The Daily Wire: the Sites a profile made for movies starts
    with."""
    return sorted(
        key for key in known_site_keys(connection)
        if any(source.has(Feature.MOVIES) for source in _fetching_sources(key))
    )


def profile_offered_for_site(s: Session, profile, site_key: str | None) -> bool:
    """Whether the profile is offered for media from the Site. A Site VODLoft has not seen yet is offered every
    profile that includes upcoming Sites; it joins their Sites once VODLoft records it. Media whose Site is
    not known yet is offered every profile."""
    if site_key is None or site_key in profile.site_keys:
        return True
    return (
        profile.include_upcoming_sites and site_offered_for_type(profile.type, site_key)
        and site_key not in known_site_keys(s)
    )


def add_upcoming_site(s: Session, site_key: str) -> None:
    """A Site VODLoft sees for the first time joins every profile that includes upcoming Sites."""
    from backend.db.models import LocalMediaProfileBase

    for profile in s.scalars(select(LocalMediaProfileBase).where(LocalMediaProfileBase.include_upcoming_sites.is_(True))):
        if site_key not in profile.site_keys and site_offered_for_type(profile.type, site_key):
            profile.site_keys = [*profile.site_keys, site_key]


@dataclass(frozen=True)
class ProfileSite:
    """A Site VODLoft knows, with the profile types that can store media from it."""

    key: str
    name: str
    profile_types: list[LocalMediaProfileType]
    download_options: DownloadOptions
    settings: list[SiteSetting]
    """The settings only some Sites show that apply to this Site, such as YouTube's SponsorBlock."""


@dataclass(frozen=True)
class ProfileSites:
    sites: list[ProfileSite]
    upcoming_profile_types: list[LocalMediaProfileType]
    """The profile types Sites VODLoft has not seen yet can bring media for."""
    upcoming_download_options: DownloadOptions
    upcoming_settings: list[SiteSetting]
    """The settings only some Sites show that apply to a Site VODLoft has not seen yet."""
    defaults: dict[str, Any]
    """What a new profile starts with for the settings only some Sites show."""


def profile_sites(s: Session) -> ProfileSites:
    """Every Site a Local Media Profile can be offered for."""
    from backend.services.site_settings import local_media_profile_defaults, offered_settings

    types = list(_PROFILE_TYPE_FEATURES)
    sites = []
    for known in known_sites(s):
        offered = [profile_type for profile_type in types if site_offered_for_type(profile_type, known.key)]
        if not offered:
            continue
        site = replace(site_of(known.key), key=known.key, name=known.name)
        sites.append(ProfileSite(
            site.key, site.name, offered, site.downloads, offered_settings(site, SiteSettingGroup.LOCAL_MEDIA_PROFILE),
        ))
    upcoming = [profile_type for profile_type in types if takes_upcoming_sites(profile_type)]
    upcoming_settings = {
        key for site in _upcoming_sites() for key in offered_settings(site, SiteSettingGroup.LOCAL_MEDIA_PROFILE)
    }
    return ProfileSites(
        sites, upcoming, _upcoming_downloads(),
        [key for key in SiteSetting if key in upcoming_settings], local_media_profile_defaults(),
    )


def profile_download_options(
        profile_type: LocalMediaProfileType | str, site_keys: Iterable[str] | None, include_upcoming_sites: bool,
) -> DownloadOptions:
    """What a profile can download: everything one of the Sites it is offered for can. Without a list yet, a new
    profile gets every Site, so it can download whatever a Source for its type can."""
    if site_keys is None:
        return DownloadOptions.combined(
            source.download_options for source in all_sources() if _stores_type(source, profile_type)
        )
    options = [site_of(key).downloads for key in site_keys if site_offered_for_type(profile_type, key)]
    if include_upcoming_sites and takes_upcoming_sites(profile_type):
        options.append(_upcoming_downloads(profile_type))
    return DownloadOptions.combined(options)


def offers_format(options: DownloadOptions, preferred_format: PreferredFormat | str) -> bool:
    preferred_format = PreferredFormat(preferred_format)
    if preferred_format == PreferredFormat.FORMAT_HLS:
        return options.hls_bundle
    if preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY:
        return options.audio_only
    return PREFERRED_FORMAT_HEIGHTS[preferred_format] in options.video_heights


def format_for_site(site: Site, preferred_format: str) -> str:
    """What a profile downloads from one Site: its own choice where the Site offers it, otherwise the
    nearest video. A profile offered for several Sites can choose what only some of them have, such
    as The Daily Wire's HLS bundle, whose highest resolution is 1080p. On a Site with sound only, which has no video, it is the sound."""
    options = site.downloads
    if preferred_format == PreferredFormat.FORMAT_AUDIO_ONLY.value or offers_format(options, preferred_format):
        return preferred_format
    if not options.video_heights:
        return PreferredFormat.FORMAT_AUDIO_ONLY.value
    wanted = 1080 if preferred_format == PreferredFormat.FORMAT_HLS.value else PREFERRED_FORMAT_HEIGHTS[PreferredFormat(preferred_format)]
    fitting = [height for height in options.video_heights if height <= wanted]
    height = max(fitting) if fitting else min(options.video_heights)
    return next(fmt.value for fmt, value in PREFERRED_FORMAT_HEIGHTS.items() if value == height)
