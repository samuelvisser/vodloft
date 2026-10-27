from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.api.models.source import (
    ApiStatusAPIRead, ProgramStatusAPIRead, SourceProblemAPIRead, ResolvedLinkAPIRead, ResolvedLinkPreviewAPIRead, SearchResultsAPIRead, ShowDetailsAPIRead,
    SourceAPIRead, SourceDomainAPIRead,
)
from backend.db.models import Episode, Show, SourceDomainPreference
from backend.services.source_requests import asking_source
from backend.utils.helpers import slugify
from sources import (
    Feature, LinkKind, ResolvedLink, Source, UnknownSourceError, all_sources, get_source, named_domains, sources_for,
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


def lookup_show_details(source: Source, url: str) -> ShowDetailsAPIRead:
    """Look up a show to add, shaped like the fields of a new show."""
    with asking_source(f"{source.name} could not look up this show"):
        details = source.show_details(url)
    author = details.author_name or details.title
    return ShowDetailsAPIRead(
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


def search_source(source: Source, query: str) -> SearchResultsAPIRead:
    with asking_source(f"{source.name} could not be searched"):
        answer = source.search(query)
    return SearchResultsAPIRead.model_validate(answer)


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
    """The Source's API status, given its shows so it can say what checking them costs."""
    shows = (
        s.query(Show.sharing_url, func.count(Episode.id))
        .outerjoin(Episode, Episode.show_id == Show.id)
        .filter(Show.source_key == source.id)
        .group_by(Show.id)
        .all()
    )
    return ApiStatusAPIRead.model_validate(source.api_status([(url, count) for url, count in shows]))


def _show_of_local_episode(s: Session, source: Source, episode_slug: str) -> Show | None:
    episode = (
        s.query(Episode)
        .filter(Episode.source_key == source.id, Episode.slug == episode_slug)
        .one_or_none()
    )
    return episode.show if episode is not None else None


def _to_read(s: Session, source: Source, link: ResolvedLink, candidates: list[Source]) -> ResolvedLinkAPIRead:
    show_slug, show_url = link.show_slug, link.show_url
    if link.kind is LinkKind.EPISODE and show_slug is None:
        local_show = _show_of_local_episode(s, source, link.slug)
        if local_show is not None:
            show_slug, show_url = local_show.slug, local_show.sharing_url
    return ResolvedLinkAPIRead(
        source=SourceAPIRead.model_validate(source),
        kind=link.kind,
        slug=link.slug,
        url=link.url,
        show_slug=show_slug,
        show_url=show_url,
        site=link.site,
        drm_protected=link.drm_protected,
        preview=ResolvedLinkPreviewAPIRead.model_validate(link),
        candidates=[SourceAPIRead.model_validate(candidate) for candidate in candidates],
    )


def preferred_sources(s: Session) -> dict[str, str]:
    return {row.domain: row.source_key for row in s.query(SourceDomainPreference)}


def resolve_link(s: Session, url: str, source_key: str | None = None) -> ResolvedLinkAPIRead:
    """Ask each Source that claims the link, preferred first, until one recognises it.

    With ``source_key`` only that Source is asked.
    """
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    candidates = sources_for(url, preferred_sources(s))
    asked = candidates
    if source_key is not None:
        asked = [source for source in candidates if source.id == source_key]
        if not asked:
            raise LinkNotRecognisedError(f"Source '{source_key}' does not handle links on this site")
    for source in asked:
        with asking_source(f"{source.name} could not look up this link"):
            link = source.resolve(url)
        if link is not None:
            return _to_read(s, source, link, candidates)
    raise LinkNotRecognisedError("No Source recognises this link")


def _domain_read(domain: str, preferred: dict[str, str]) -> SourceDomainAPIRead:
    candidates = sources_for(f"https://{domain}/")
    return SourceDomainAPIRead(
        domain=domain,
        source_keys=[source.id for source in candidates],
        default_source_key=candidates[0].id,
        preferred_source_key=preferred.get(domain),
    )


def list_source_domains(s: Session) -> list[SourceDomainAPIRead]:
    """Every domain a Source names, with the Sources that can handle it."""
    preferred = preferred_sources(s)
    return [_domain_read(domain, preferred) for domain in named_domains()]


class UnknownDomainError(LookupError):
    pass


def set_domain_preference(s: Session, domain: str, source_key: str | None) -> SourceDomainAPIRead:
    domain = domain.strip().lower()
    if domain not in named_domains():
        raise UnknownDomainError(f"No Source names the domain '{domain}'")
    current = s.get(SourceDomainPreference, domain)
    if source_key is None:
        if current is not None:
            s.delete(current)
    else:
        if source_key not in [source.id for source in sources_for(f"https://{domain}/")]:
            raise UnknownDomainError(f"Source '{source_key}' does not handle links on {domain}")
        if current is None:
            s.add(SourceDomainPreference(domain=domain, source_key=source_key))
        else:
            current.source_key = source_key
    s.flush()
    return _domain_read(domain, preferred_sources(s))
