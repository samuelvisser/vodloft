from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.api.models.source import ResolvedLinkAPIRead, ResolvedLinkPreviewAPIRead, SourceAPIRead
from backend.db.models import Episode, Show
from config.network import is_no_internet_error
from sources import LinkKind, ResolvedLink, Source, all_sources, sources_for


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


def _show_of_local_episode(s: Session, source: Source, episode_slug: str) -> Show | None:
    episode = (
        s.query(Episode)
        .filter(Episode.source_key == source.id, Episode.slug == episode_slug)
        .one_or_none()
    )
    return episode.show if episode is not None else None


def _to_read(s: Session, source: Source, link: ResolvedLink) -> ResolvedLinkAPIRead:
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
        preview=ResolvedLinkPreviewAPIRead(
            title=link.title,
            description=link.description,
            image_url=link.image_url,
            author_name=link.author_name,
        ),
    )


def resolve_link(s: Session, url: str) -> ResolvedLinkAPIRead:
    """Ask each Source that claims the link, in order, until one recognises it."""
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    for source in sources_for(url):
        try:
            link = source.resolve(url)
        except Exception as exc:
            if is_no_internet_error(exc):
                raise
            logger.warning("Source %s could not look up %s: %s", source.id, url, exc)
            raise SourceLookupError(source, f"{source.name} could not look up this link: {exc}") from exc
        if link is not None:
            return _to_read(s, source, link)
    raise LinkNotRecognisedError("No Source recognises this link")
