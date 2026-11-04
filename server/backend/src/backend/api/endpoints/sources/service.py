from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.api.models.source import (
    ApiStatusAPIRead, ProgramStatusAPIRead, SourceProblemAPIRead, ResolvedLinkAPIRead, ResolvedLinkPreviewAPIRead, SearchResultsAPIRead, CollectionDetailsAPIRead,
    SourceAPIRead, SourceSiteAPIRead,
)
from backend.db.models import Episode, Collection
from backend.security.access import Access
from backend.services.sites import preferred_sources, site_record
from backend.services.source_requests import asking_source
from backend.utils.helpers import slugify
from sources import (
    Feature, LinkKind, ResolvedLink, Site, Source, UnknownSourceError, all_sources, get_source, named_sites, sources_for,
)


logger = logging.getLogger(__name__)


class LinkNotRecognisedError(LookupError):
    pass


def list_sources() -> list[SourceAPIRead]:
    return [SourceAPIRead.model_validate(source) for source in all_sources()]


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
        seasons=details.seasons,
    )


def search_source(access: Access, source: Source, query: str) -> SearchResultsAPIRead:
    """Search a Source, leaving out results on domains the user may not use."""
    access.check_source(source)
    with asking_source(f"{source.name} could not be searched"):
        answer = source.search(query)
    results = SearchResultsAPIRead.model_validate(answer)
    return results.model_copy(update={
        "results": [result for result in results.results if access.allows_link(source.id, result.url)],
    })


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
    """The Source's API status, given its collections so it can say what checking them costs."""
    collections = (
        s.query(Collection.sharing_url, func.count(Episode.id))
        .outerjoin(Episode, Episode.collection_id == Collection.id)
        .filter(Collection.source_key == source.id)
        .group_by(Collection.id)
        .all()
    )
    return ApiStatusAPIRead.model_validate(source.api_status([(url, count) for url, count in collections]))


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
    return ResolvedLinkAPIRead(
        source=SourceAPIRead.model_validate(source),
        kind=link.kind,
        slug=link.slug,
        url=link.url,
        collection_slug=collection_slug,
        collection_url=collection_url,
        site=link.site,
        drm_protected=link.drm_protected,
        needs_subscription=link.needs_subscription,
        preview=ResolvedLinkPreviewAPIRead.model_validate(link),
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
