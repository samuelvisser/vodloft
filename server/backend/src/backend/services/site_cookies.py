"""Authentication per Site: a Site's own sign-in, such as The Daily Wire's, a cookies file per Site,
and the API key a Source uses on a Site, such as YouTube's.

Every Source that signs in with cookies uses the cookies file of the Site it fetches, so YouTube and Twitch
each have their own file, and yt-dlp uses NPO Start's file when it fetches npo.nl. A cookies file that another
program kept for every site, such as yt-dlp's old one or Pinchflat's, is sorted into the Sites: each Site gets
the cookies for its own domains.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Optional
from urllib.parse import unquote

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import get_session, run_write_transaction
from backend.db.models import Site as SiteRecord
from backend.services.sites import SiteLinkError, site_of_link, site_record
from sources import ANY_DOMAIN, CookiesStatus, Feature, Site, Source, all_sources, named_sites, site_of, sources_for
from sources import cookies as cookie_files

logger = logging.getLogger(__name__)

GENERIC_PREFIX = "generic:"
"""The start of the key of a Site no Source knows, named after its domain."""


class SiteNotKnownError(LookupError):
    pass


@dataclass(frozen=True)
class SiteAuthentication:
    """A Site, and how VODLoft signs in on it or gets at its API."""

    key: str
    name: str
    domains: tuple[str, ...]
    sign_in_source_key: Optional[str]
    """The Source made for the Site that has a sign-in of its own, such as The Daily Wire's."""
    cookie_source_keys: tuple[str, ...]
    """The Sources that sign in on the Site with its cookies file."""
    cookie_source_names: tuple[str, ...]
    cookies_help: Optional[str]
    cookie_count: int
    """How many cookies the Site's cookies file holds; 0 without one."""
    cookies_status: Optional[CookiesStatus]
    api_key_source_key: Optional[str]
    """The Source whose API key is for the Site, such as yt-dlp's YouTube Data API key."""

    @property
    def has_cookies(self) -> bool:
        return self.cookie_count > 0


@dataclass(frozen=True)
class SortedSite:
    key: str
    name: str
    cookie_count: int


@dataclass(frozen=True)
class SortedCookies:
    """Where the cookies of one file went: the Sites that got some, and the domains no Site has."""

    sites: tuple[SortedSite, ...]
    other_domains: tuple[str, ...]


def _known_sites(s: Session) -> dict[str, tuple[Site, tuple[str, ...]]]:
    """Every Site VODLoft knows, with every domain it knows for it: the Sites a Source is made for or
    takes an API key for, the Sites it has seen, and the Sites that still have a cookies file."""
    found: dict[str, tuple[Site, tuple[str, ...]]] = {site.key: (site, site.domains) for site in named_sites()}
    for source in all_sources():
        if source.has(Feature.API_KEY):
            for site in source.api_key_sites:
                found.setdefault(site.key, (site, site.domains))
    for record in s.scalars(select(SiteRecord)).all():
        site, domains = found.get(record.key, (site_of(record.key), ()))
        merged = tuple(dict.fromkeys((*domains, *record.domains)))
        found[record.key] = (replace(site, key=record.key, name=record.name, domains=merged), merged)
    directory = cookie_files.cookies_directory()
    if directory.is_dir():
        for path in directory.glob("*.txt"):
            key = unquote(path.stem)
            if key not in found:
                site = site_of(key)
                found[key] = (site, site.domains)
    return found


def _cookie_sources(site: Site, domains: tuple[str, ...]) -> list[Source]:
    """The Sources that sign in with cookies on the Site, with these domains; none on a Site that takes no cookies."""
    if not site.takes_cookies:
        return []
    candidates = sources_for(f"https://{domains[0]}/") if domains else [
        source for source in all_sources() if ANY_DOMAIN in source.domains
    ]
    return [source for source in candidates if source.has(Feature.COOKIES)]


def _cookie_count(site_key: str) -> int:
    path = cookie_files.site_cookies(site_key)
    if path is None:
        return 0
    try:
        return len(cookie_files.cookie_lines(path.read_text(errors="replace")))
    except OSError:
        return 0


def _status(site_key: str, sources: list[Source]) -> Optional[CookiesStatus]:
    return next((status for source in sources if (status := source.cookies_status(site_key)) is not None), None)


def _authentication(site: Site, domains: tuple[str, ...]) -> SiteAuthentication:
    sources = _cookie_sources(site, domains)
    count = _cookie_count(site.key)
    owner = next(
        (source for source in all_sources() if source.has(Feature.LOGIN) and any(own.key == site.key for own in source.sites)),
        None,
    )
    api_key = next(
        (source for source in (sources_for(f"https://{domains[0]}/") if domains and site.takes_api_key else [])
         if source.has(Feature.API_KEY)),
        None,
    )
    return SiteAuthentication(
        key=site.key, name=site.name, domains=domains, sign_in_source_key=owner.id if owner is not None else None,
        cookie_source_keys=tuple(source.id for source in sources),
        cookie_source_names=tuple(source.name for source in sources), cookies_help=site.cookies_help,
        cookie_count=count, cookies_status=_status(site.key, sources) if count else None,
        api_key_source_key=api_key.id if api_key is not None else None,
    )


def list_site_authentication(s: Session) -> list[SiteAuthentication]:
    """Every Site VODLoft knows, with how it signs in there. Sites with a sign-in, cookies or an API key come first."""
    listings = [_authentication(site, domains) for site, domains in _known_sites(s).values()]
    return sorted(listings, key=lambda listing: (
        not (listing.sign_in_source_key or listing.has_cookies or listing.api_key_source_key), listing.name.lower(),
    ))


def site_authentication(s: Session, site_key: str) -> SiteAuthentication:
    known = _known_sites(s)
    if site_key not in known:
        raise SiteNotKnownError(f"VODLoft does not know the Site '{site_key}'")
    return _authentication(*known[site_key])


def _changed(site: Site, domains: tuple[str, ...]) -> None:
    for source in _cookie_sources(site, domains):
        source.cookies_changed(site.key)


def save_site_cookies(s: Session, site_key: str, content: bytes) -> SiteAuthentication:
    """Keep the Site's cookies of a cookies file as the Site's cookies file.

    Raises ValueError for a file that is no cookies file, or has no cookies for the Site.
    """
    known = _known_sites(s)
    if site_key not in known:
        raise SiteNotKnownError(f"VODLoft does not know the Site '{site_key}'")
    site, domains = known[site_key]
    if not site.takes_cookies:
        raise ValueError(f"{site.name} takes no cookies file; it has a sign-in of its own")
    lines = cookie_files.cookie_lines(cookie_files.cookies_text(content))
    if domains:
        lines = [line for line in lines if cookie_files.on_site(line, domains)]
        if not lines:
            raise ValueError(
                f"This cookies file has no cookies for {domains[0]}. Export it while signed in on {domains[0]}."
            )
    cookie_files.store_site_cookies(site_key, lines)
    _changed(site, domains)
    logger.info("Stored a cookies file for %s with %s cookies", site.name, len(lines))
    return _authentication(site, domains)


def remove_site_cookies(s: Session, site_key: str) -> SiteAuthentication:
    known = _known_sites(s)
    if site_key not in known:
        raise SiteNotKnownError(f"VODLoft does not know the Site '{site_key}'")
    site, domains = known[site_key]
    cookie_files.remove_site_cookies(site_key)
    _changed(site, domains)
    return _authentication(site, domains)


def sites_for_cookies(s: Session, content: bytes) -> list[Site]:
    """The Sites VODLoft does not know yet that a cookies file has cookies for, where the domain alone tells
    the Site, such as youtube.com. A domain that tells no Site of its own, such as twitch.tv, is left out:
    its Site is known once it is added by a link. Raises ValueError for a file that is no cookies file."""
    lines = cookie_files.cookie_lines(cookie_files.cookies_text(content))
    known = _known_sites(s)
    known_domains = [domain for _, domains in known.values() for domain in domains]
    found: dict[str, Site] = {}
    for domain in sorted({cookie_files.cookie_domain(line) for line in lines}):
        if cookie_files.shares_domain(domain, known_domains):
            continue
        try:
            site = site_of_link(s, f"https://{domain}/")
        except SiteLinkError:
            continue
        if not site.key.startswith(GENERIC_PREFIX) and site.key not in known:
            found.setdefault(site.key, site)
    return list(found.values())


def add_cookies_file(content: bytes) -> SortedCookies:
    """Give every Site the cookies of one cookies file that are for its domains, after adding the Sites
    the file's domains tell. Raises ValueError for a file that is no cookies file."""
    with _reading() as s:
        new = sites_for_cookies(s, content)
    if new:
        run_write_transaction(lambda s: add_sites(s, new))
    with _reading() as s:
        return sort_cookies(s, content)


def add_sites(s: Session, sites: list[Site]) -> None:
    for site in sites:
        site_record(s, site)


@contextmanager
def _reading() -> Iterator[Session]:
    s = get_session()
    try:
        yield s
    finally:
        s.close()


def sort_cookies(s: Session, content: bytes) -> SortedCookies:
    """Give every Site the cookies of one cookies file that are for its domains, in place of the ones it had.

    A Site without cookies in the file keeps its own cookies file. Raises ValueError for a file that
    is no cookies file.
    """
    lines = cookie_files.cookie_lines(cookie_files.cookies_text(content))
    placed: set[str] = set()
    sorted_sites = []
    for site, domains in _known_sites(s).values():
        if not domains or not site.takes_cookies:
            continue
        own = [line for line in lines if cookie_files.on_site(line, domains)]
        if not own:
            continue
        cookie_files.store_site_cookies(site.key, own)
        _changed(site, domains)
        placed.update(own)
        sorted_sites.append(SortedSite(site.key, site.name, len(own)))
    other = sorted({cookie_files.cookie_domain(line) for line in lines if line not in placed})
    if sorted_sites:
        logger.info("Sorted a cookies file into %s", ", ".join(site.name for site in sorted_sites))
    return SortedCookies(tuple(sorted(sorted_sites, key=lambda site: site.name.lower())), tuple(other))
