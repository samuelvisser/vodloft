from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.api.models.source import (
    ProgramStatusAPIRead, ResolvedLinkAPIRead, ResolvedLinkPreviewAPIRead, SourceAPIRead, SourceDomainAPIRead,
)
from backend.db.models import Episode, Show, SourceDomainPreference
from config.network import is_no_internet_error
from sources import (
    Feature, LinkKind, ProgramStatus, ResolvedLink, Source, UnknownSourceError, all_sources, get_source, named_domains,
    sources_for,
)


logger = logging.getLogger(__name__)


class LinkNotRecognisedError(LookupError):
    pass


class SourceLookupError(RuntimeError):
    def __init__(self, source: Source, message: str):
        super().__init__(message)
        self.source = source


def to_source_read(source: Source) -> SourceAPIRead:
    return SourceAPIRead(
        id=source.id,
        name=source.name,
        domains=list(source.domains),
        features=sorted(feature.value for feature in source.features),
    )


def list_sources() -> list[SourceAPIRead]:
    return [to_source_read(source) for source in all_sources()]


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


def to_program_read(status: ProgramStatus) -> ProgramStatusAPIRead:
    return ProgramStatusAPIRead(
        name=status.name, version=status.version,
        last_update_at=status.last_update_at, last_update_error=status.last_update_error,
    )


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
        source=to_source_read(source),
        kind=link.kind.value,
        slug=link.slug,
        url=link.url,
        show_slug=show_slug,
        show_url=show_url,
        site=link.site,
        drm_protected=link.drm_protected,
        preview=ResolvedLinkPreviewAPIRead(
            title=link.title,
            description=link.description,
            image_url=link.image_url,
            author_name=link.author_name,
        ),
        candidates=[to_source_read(candidate) for candidate in candidates],
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
        try:
            link = source.resolve(url)
        except Exception as exc:
            if is_no_internet_error(exc):
                raise
            logger.warning("Source %s could not look up %s: %s", source.id, url, exc)
            raise SourceLookupError(source, f"{source.name} could not look up this link: {exc}") from exc
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
