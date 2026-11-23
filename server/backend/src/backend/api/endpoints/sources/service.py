from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.models.source import (
    ApiKeyNoteAPIRead, ApiStatusAPIRead, ProgramStatusAPIRead, SourceProblemAPIRead, ResolvedLinkAPIRead, ResolvedLinkPreviewAPIRead, SearchResultsAPIRead, CollectionDetailsAPIRead,
    SourceAPIRead, SourceSiteAPIRead,
)
from backend.db.models import Collection, CreatorAccount, Episode, MediaItemBase, Settings, Site as SiteRecord
from backend.security.access import Access
from backend.types.collection_types import CollectionType
from backend.services.collections import set_kind
from backend.services.creators import takes_creators
from backend.services.link_seasons import seasons_plan
from backend.services.media_access import access_locked, link_access
from backend.services.sites import collection_kind, preferred_sources, site_record
from backend.services.source_requests import asking_source
from config.network import is_no_internet_error
from backend.services.users import settings_row
from backend.services.check_frequency import joins_regular_checks, quick_check_plan
from backend.utils.helpers import slugify
from sources import (
    Feature, LinkKind, QuickCheckCollection, ResolvedLink, Site, Source, UnknownSourceError, all_sources, get_source, named_sites, names_a_podcast, source_site, sources_for,
)


logger = logging.getLogger(__name__)


class LinkNotRecognisedError(LookupError):
    pass


def list_sources(s: Session) -> list[SourceAPIRead]:
    """Every Source, with which of the Sites it searches are added to VODLoft, and which it can search now."""
    added = set(s.scalars(select(SiteRecord.key)))
    return [
        SourceAPIRead.model_validate(source, context={
            "added_sites": added,
            "ready_sites": {site.key for site in source.search_sites if source.search_ready(site)},
        })
        for source in all_sources()
    ]


def sources_in_use(s: Session) -> list[str]:
    """The ids of the Sources the Library has collections, creators, movies or videos from."""
    return sorted(s.scalars(
        select(Collection.source_key)
        .union(select(CreatorAccount.source_key), select(MediaItemBase.source_key))
    ).all())


class SourceFeatureMissingError(LookupError):
    pass


def source_with(source_id: str, feature: Feature) -> Source:
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise SourceFeatureMissingError(str(exc)) from exc
    if not source.has(feature):
        raise SourceFeatureMissingError(f"{source.name} does not support this")
    return source


def lookup_show_details(access: Access, source: Source, url: str) -> CollectionDetailsAPIRead:
    """Look up a collection to add, shaped like the fields of a new collection."""
    access.check_link(source, url)
    with asking_source(f"{source.name} could not look up this collection"):
        details = source.collection_details(url)
    try:
        music = source.music_reason(url, details)
    except Exception as exc:  # A guess: a failed look leaves the type to the name.
        if is_no_internet_error(exc):
            raise
        logger.info("Could not tell whether %s is music: %s", url, exc)
        music = None
    author = details.author_name or details.title
    return CollectionDetailsAPIRead(
        source_key=source.id,
        slug=details.slug,
        title=details.title,
        description=details.description,
        sharing_url=details.url,
        author_name=author,
        author_slug=slugify(author) or details.slug,
        thumbnail_landscape_path=details.image_url,
        probable_collection_type=(
            CollectionType.MUSIC if music else CollectionType.PODCAST if names_a_podcast(details.title) else CollectionType.SERIES
        ),
        music_reason=music,
        seasons=details.seasons,
        audio_only=source_site(details.url, source.id).audio_only,
        kind=collection_kind(details.url, source.id),
        list_type=details.list_type,
        seasons_plans={type_.value: _seasons_plan(source, details.url, type_) for type_ in CollectionType},
    )


def _seasons_plan(source: Source, url: str, type_: CollectionType) -> str:
    """What the collection's seasons will be once it is added as the type, as adding it sets it up."""
    collection = Collection(sharing_url=url, source_key=source.id, type=type_.value)
    set_kind(collection)
    return seasons_plan(collection)


def search_source(access: Access, source: Source, site_key: str, query: str) -> SearchResultsAPIRead:
    """Search one of a Source's search Sites, leaving out results on domains the user may not use."""
    access.check_source(source)
    site = next((site for site in source.search_sites if site.key == site_key), None)
    if site is None:
        raise SourceFeatureMissingError(f"{source.name} cannot search {site_key}")
    with asking_source(f"{site.name} could not be searched"):
        answer = source.search(site, query)
    results = SearchResultsAPIRead.model_validate(answer)
    return results.model_copy(update={
        "results": [
            result.model_copy(update={
                "access_label": _access_label(source, result.url, result.access),
            })
            for result in results.results if access.allows_link(source.id, result.url)
        ],
    })


def _access_label(source: Source, url: str, key: str | None) -> str | None:
    found = link_access(source.id, url, key)
    return found.label if found is not None else None


def get_program_status(source: Source) -> ProgramStatusAPIRead:
    return ProgramStatusAPIRead.model_validate(source.program_status())


def update_source_program(source: Source) -> ProgramStatusAPIRead:
    with asking_source(f"Could not update {source.name}"):
        status = source.update_program()
    return ProgramStatusAPIRead.model_validate(status)


def list_source_problems() -> list[SourceProblemAPIRead]:
    return [
        SourceProblemAPIRead(source_key=source.id, source_name=source.name, **vars(problem))
        for source in all_sources()
        for problem in source.problems()
    ]


def get_api_status(s: Session, source: Source) -> ApiStatusAPIRead:
    """The Source's API status, given the collections it checks so it can say what checking them costs."""
    counts = dict(
        s.query(Episode.collection_id, func.count(Episode.id))
        .join(Collection, Collection.id == Episode.collection_id)
        .filter(Collection.source_key == source.id)
        .group_by(Episode.collection_id)
        .all()
    )
    collections = s.scalars(
        select(Collection).where(Collection.source_key == source.id, Collection.sharing_url.is_not(None))
    ).all()
    plans = [
        quick_check_plan(collection, counts.get(collection.id, 0))
        for collection in collections if joins_regular_checks(collection)
    ]
    return ApiStatusAPIRead.model_validate(source.api_status(plans))


API_KEY_NOTE_PAUSE = timedelta(days=7)
"""How long Remind me later puts off the note that asks for an API key."""


def api_key_notes(s: Session) -> list[ApiKeyNoteAPIRead]:
    """The Sources whose API key would speed up collections or creators in the Library while they have none, unless
    the user put the note off or turned it off."""
    settings = s.scalars(select(Settings).order_by(Settings.id).limit(1)).first()
    if settings is not None and (
        settings.api_key_note_off
        or (settings.api_key_note_after is not None and settings.api_key_note_after > datetime.now(timezone.utc))
    ):
        return []
    notes = []
    for source in all_sources():
        if not source.has(Feature.API_KEY):
            continue
        links = s.scalars(
            select(Collection.sharing_url).where(Collection.source_key == source.id, Collection.sharing_url.is_not(None))
            .union(select(CreatorAccount.url).where(CreatorAccount.source_key == source.id, CreatorAccount.url.is_not(None)))
        ).all()
        status = source.api_status([QuickCheckCollection(link) for link in links])
        site = next((site for link in links if (site := source.site_for(link)) is not None and site.takes_api_key), None)
        if status.key_hint is None and status.collection_count and site is not None:
            notes.append(ApiKeyNoteAPIRead(source_key=source.id, site_name=site.name))
    return notes


def put_off_api_key_note(s: Session, action: str) -> None:
    """Put the note that asks for an API key off for a while, or turn it off."""
    settings = settings_row(s)
    if action == "never":
        settings.api_key_note_off = True
    else:
        settings.api_key_note_after = datetime.now(timezone.utc) + API_KEY_NOTE_PAUSE


def _collection_of_local_episode(s: Session, source: Source, episode_slug: str) -> Collection | None:
    episode = (
        s.query(Episode)
        .filter(Episode.source_key == source.id, Episode.slug == episode_slug)
        .one_or_none()
    )
    return episode.collection if episode is not None else None


def _to_read(s: Session, source: Source, link: ResolvedLink, candidates: list[Source]) -> ResolvedLinkAPIRead:
    collection_slug, collection_url = link.collection_slug, link.collection_url
    if link.kind is LinkKind.EPISODE and collection_slug is None:
        local_collection = _collection_of_local_episode(s, source, link.slug)
        if local_collection is not None:
            collection_slug, collection_url = local_collection.slug, local_collection.sharing_url
    found = link_access(source.id, link.url, link.access)
    kind = collection_kind(link.url, source.id) if link.kind is LinkKind.COLLECTION else None
    site = source_site(link.url, source.id) if kind is not None else None
    return ResolvedLinkAPIRead(
        source=SourceAPIRead.model_validate(source),
        kind=link.kind,
        slug=link.slug,
        url=link.url,
        collection_slug=collection_slug,
        collection_url=collection_url,
        site=link.site,
        drm_protected=link.drm_protected,
        access=link.access,
        access_label=found.label if found is not None else None,
        access_description=found.description if found is not None else None,
        access_locked=access_locked(source.id, link.access, None),
        preview=ResolvedLinkPreviewAPIRead.model_validate(link),
        collection_kind=kind,
        creator_names=site.creator_names if site is not None and takes_creators(source.id, site) else None,
        candidates=[SourceAPIRead.model_validate(candidate) for candidate in candidates],
    )


def resolve_link(s: Session, access: Access, url: str, source_key: str | None = None) -> ResolvedLinkAPIRead:
    """Ask each Source that claims the link, preferred first, until one recognises it.

    With ``source_key`` only that Source is asked. Only Sources and domains the
    user may use are asked, and the link the Source resolves to must be one the
    user may use too, so a link cannot redirect them somewhere else.
    """
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    candidates = sources_for(url, preferred_sources(s))
    allowed = [source for source in candidates if access.allows_link(source.id, url)]
    if source_key is not None:
        asked = [source for source in candidates if source.id == source_key]
        if not asked:
            raise LinkNotRecognisedError(f"Source '{source_key}' does not handle links on this site")
        access.check_link(asked[0], url)
    else:
        if candidates and not allowed:
            # Name the domain when the user may use one of the Sources, otherwise the Source.
            usable = [source for source in candidates if access.allows_source(source.id)]
            access.check_link((usable or candidates)[0], url)
        asked = allowed
    for source in asked:
        with asking_source(f"{source.name} could not look up this link"):
            link = source.resolve(url)
        if link is not None:
            access.check_link(source, link.url)
            return _to_read(s, source, link, allowed)
    if source_key is not None:
        raise LinkNotRecognisedError(f"{asked[0].name} does not recognise this link")
    raise LinkNotRecognisedError("No Source recognises this link")


def _site_read(site: Site, preferred: dict[str, str]) -> SourceSiteAPIRead:
    candidates = sources_for(f"https://{site.domains[0]}/")
    return SourceSiteAPIRead(
        key=site.key,
        name=site.name,
        domains=list(site.domains),
        source_keys=[source.id for source in candidates],
        default_source_key=candidates[0].id,
        preferred_source_key=preferred.get(site.key),
    )


def list_source_sites(s: Session) -> list[SourceSiteAPIRead]:
    """Every Site a Source is made for, with the Sources that can handle its links."""
    preferred = preferred_sources(s)
    return [_site_read(site, preferred) for site in named_sites()]


class UnknownSiteError(LookupError):
    pass


def set_site_preference(s: Session, key: str, source_key: str | None) -> SourceSiteAPIRead:
    site = next((site for site in named_sites() if site.key == key), None)
    if site is None:
        raise UnknownSiteError(f"No Source is made for the Site '{key}'")
    if source_key is not None and source_key not in [source.id for source in sources_for(f"https://{site.domains[0]}/")]:
        raise UnknownSiteError(f"Source '{source_key}' does not handle links on {site.name}")
    site_record(s, site).preferred_source_key = source_key
    s.flush()
    return _site_read(site, preferred_sources(s))
