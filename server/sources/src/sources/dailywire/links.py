"""Which Daily Wire page a link points to."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..contract import LinkKind, ResolvedLink
from .api.dw_api.client import MiddlewareClient
from .api.dw_api.movie import MovieMiddlewareClient
from .auth import DeviceAuthClient

SITE_URL = "https://www.dailywire.com"

_KIND_BY_SECTION = {
    "show": LinkKind.SHOW,
    "shows": LinkKind.SHOW,
    "videos": LinkKind.MOVIE,
    "movie": LinkKind.MOVIE,
    "movies": LinkKind.MOVIE,
    "episode": LinkKind.EPISODE,
    "episodes": LinkKind.EPISODE,
}


def parse_link(url: str) -> tuple[LinkKind, str] | None:
    """The kind and slug of a dailywire.com link, from its path alone."""
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if len(parts) < 2:
        return None
    kind = _KIND_BY_SECTION.get(parts[0].lower())
    if kind is None:
        return None
    return kind, parts[1]


def _access_token() -> str | None:
    tokens = DeviceAuthClient().get_token()
    return tokens.access_token if tokens else None


def _first(*values: Any) -> str | None:
    return next((value for value in values if isinstance(value, str) and value), None)


def show_url(slug: str) -> str:
    return f"{SITE_URL}/show/{slug}"


def resolve_link(url: str) -> ResolvedLink | None:
    parsed = parse_link(url)
    if parsed is None:
        return None
    kind, slug = parsed
    token = _access_token()

    if kind is LinkKind.SHOW:
        show = MiddlewareClient(access_token=token, request_priority="interactive").get_show_page(slug=slug)
        return ResolvedLink(
            kind=kind,
            slug=show.slug,
            url=show_url(show.slug),
            title=show.title,
            description=show.description,
            image_url=_first(show.thumbnail_portrait_path, show.thumbnail_landscape_path, show.background_image_path),
            author_name=show.author_name,
        )

    if kind is LinkKind.MOVIE:
        movie = MovieMiddlewareClient(access_token=token, request_priority="interactive").get_movie_page(slug)
        return ResolvedLink(
            kind=kind,
            slug=movie.slug,
            url=movie.sharing_url or f"{SITE_URL}/videos/{movie.slug}",
            title=movie.title,
            description=movie.description,
            image_url=_first(movie.thumbnail_portrait_path, movie.thumbnail_landscape_path, movie.background_image_path),
            author_name=movie.author_name,
        )

    payload = MiddlewareClient(access_token=token, request_priority="interactive").get_episode_payload(slug)
    show = payload.get("show") if isinstance(payload.get("show"), dict) else {}
    show_slug = _first(show.get("slug"), payload.get("showSlug"))
    images = payload.get("images") if isinstance(payload.get("images"), dict) else {}
    thumbnail = images.get("thumbnail") if isinstance(images.get("thumbnail"), dict) else {}
    return ResolvedLink(
        kind=kind,
        slug=payload.get("slug") or slug,
        url=_first(payload.get("sharingUrl")) or f"{SITE_URL}/episode/{slug}",
        title=_first(payload.get("title")) or slug,
        description=_first(payload.get("description")),
        image_url=_first(thumbnail.get("land"), thumbnail.get("port"), payload.get("backgroundImage")),
        author_name=_first((show.get("author") or {}).get("name") if isinstance(show.get("author"), dict) else None),
        show_slug=show_slug,
        show_url=show_url(show_slug) if show_slug else None,
    )
