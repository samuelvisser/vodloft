"""Which Sources exist, which Source handles a link, and which Site a link is on."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .contract import ANY_DOMAIN, Site, Source, domain_site, link_host, on_domain


class UnknownSourceError(LookupError):
    pass


_sources: dict[str, Source] = {}


def register(source: Source) -> Source:
    if source.id in _sources:
        raise ValueError(f"Source '{source.id}' is already registered")
    _sources[source.id] = source
    return source


def get_source(source_id: str) -> Source:
    try:
        return _sources[source_id]
    except KeyError:
        raise UnknownSourceError(f"No Source is registered as '{source_id}'") from None


def all_sources() -> list[Source]:
    return list(_sources.values())


def sources_for(url: str, preferred: Mapping[str, str] | None = None) -> list[Source]:
    """All Sources that claim the link's domain, in registration order.

    Sources that claim every domain (``*``) come after the ones that name it.
    ``preferred`` maps a Site's key to the Source the user prefers for it; that
    Source comes first for links on the Site.
    """
    matching = sorted(
        (source for source in _sources.values() if source.handles(url)),
        key=lambda source: ANY_DOMAIN in source.domains,
    )
    site = named_site_for(url)
    source_id = (preferred or {}).get(site.key) if site is not None else None
    if source_id is not None:
        matching.sort(key=lambda source: source.id != source_id)
    return matching


def named_sites() -> list[Site]:
    """Every Site a Source is made for, such as The Daily Wire. Other Sources may handle them too."""
    found: dict[str, Site] = {}
    for source in _sources.values():
        for site in source.sites:
            found.setdefault(site.key, site)
    return sorted(found.values(), key=lambda site: site.key)


def site_of(site_key: str) -> Site:
    """The contract for the Site with the key, told by the first Source that has one: a Source made for
    the Site, such as The Daily Wire's, comes before one that fetches any site. A Site no Source knows
    offers the defaults."""
    return next((site for source in _sources.values() if (site := source.site_of(site_key)) is not None), Site(site_key, site_key))


def named_site_for(url: str) -> Site | None:
    """The Site a Source is made for that the link is on, by the most specific domain."""
    host = link_host(url)
    matches = [
        (len(domain), site) for site in named_sites() for domain in site.domains if on_domain(host, domain)
    ]
    return max(matches, key=lambda match: match[0])[1] if matches else None


def site_for(url: str, source_id: str | None = None) -> Site:
    """The Site of a link, told without a network request.

    A Site some Source is made for wins, so a Daily Wire link is on The Daily Wire
    whichever Source fetches it. Otherwise the link's Source tells, and a link no
    Source can place is a Site of its own domain.
    """
    site = named_site_for(url)
    if site is None and source_id is not None and source_id in _sources:
        site = _sources[source_id].site_for(url)
    return site or domain_site(url)


def source_site(url: str, source_id: str) -> Site:
    """What the Source that fetches a link offers on the link's Site.

    Which Site the link is on is ``site_for``'s answer, shared by every Source. What the Site
    offers, such as countdown downloads, upgrade checks or streaming, comes from the fetching
    Source's own contract for it only: a Daily Wire link fetched with yt-dlp gets what yt-dlp
    offers, never what The Daily Wire's own Source does. A Source with no contract for the Site
    offers its defaults.
    """
    site = site_for(url, source_id)
    source = _sources.get(source_id)
    own = source.site_for(url) if source is not None else None
    return replace(own or Site(site.key, site.name), key=site.key, name=site.name, domains=site.domains)


def collection_on_site(url: str, source_id: str, source_ref: str) -> tuple[Site, str]:
    """The Site a collection is on, and the Site's own id for it.

    The same collection is the same pair whichever Source fetches it: a Source that is
    made for the Site tells the id from the link. On any other Site, the id of the
    Source that fetches it, ``source_ref``, is the Site's.
    """
    site = site_for(url, source_id)
    owner = next((source for source in _sources.values() if site in source.sites), None)
    ref = owner.collection_ref(url) if owner is not None else None
    return site, ref or source_ref
