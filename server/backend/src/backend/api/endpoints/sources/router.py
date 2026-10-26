from fastapi import APIRouter, HTTPException, Query

from backend.api.models.source import (
    CookiesAPIRead, CookiesAPIUpdate, ProgramStatusAPIRead, ResolveAPIRequest, ResolvedLinkAPIRead, SearchResultAPIRead,
    ShowDetailsAPIRead, SourceAPIRead, SourceDomainAPIRead, SourceDomainAPIUpdate,
)
from backend.app import db_session
from sources import Feature, Source

from .service import (
    LinkNotRecognisedError, SourceFeatureMissingError, UnknownDomainError, get_program_status, list_source_domains,
    list_sources, lookup_show_details, resolve_link, search_source, set_domain_preference, source_with,
    update_source_program,
)


router = APIRouter(tags=["Sources"])


def _source(source_id: str, feature: Feature) -> Source:
    try:
        return source_with(source_id, feature)
    except SourceFeatureMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sources", response_model=list[SourceAPIRead])
def source_list():
    """List every Source with the Features it supports."""
    return list_sources()


@router.get("/sources/domains", response_model=list[SourceDomainAPIRead])
def source_domains():
    """Every domain a Source names, with the Sources that can handle its links."""
    with db_session() as s:
        return list_source_domains(s)


@router.put("/sources/domains/{domain}", response_model=SourceDomainAPIRead)
def update_source_domain(domain: str, body: SourceDomainAPIUpdate):
    """Choose the Source to ask first for links on a domain."""
    with db_session() as s:
        try:
            result = set_domain_preference(s, domain, body.preferred_source_key)
        except UnknownDomainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        s.commit()
        return result


@router.post("/resolve", response_model=ResolvedLinkAPIRead)
def resolve(body: ResolveAPIRequest):
    """Find the Source that recognises a link, and what the link points to."""
    with db_session() as s:
        try:
            return resolve_link(s, body.url, body.source_key)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sources/{source_id}/show", response_model=ShowDetailsAPIRead)
def show_details(source_id: str, url: str = Query(min_length=1, max_length=2048)):
    """Look up a show to add, at a Source that lists its episodes."""
    return lookup_show_details(_source(source_id, Feature.EPISODE_LISTS), url)


@router.get("/sources/{source_id}/search", response_model=list[SearchResultAPIRead])
def search(source_id: str, q: str = Query(min_length=1, max_length=200)):
    """Find shows and videos at a Source by name."""
    return search_source(_source(source_id, Feature.SEARCH), q)


@router.get("/sources/{source_id}/program", response_model=ProgramStatusAPIRead)
def program_status(source_id: str):
    """The program a Source runs, such as yt-dlp, and when it was last updated."""
    return get_program_status(_source(source_id, Feature.PROGRAM_UPDATES))


@router.post("/sources/{source_id}/program/update", response_model=ProgramStatusAPIRead)
def update_program(source_id: str):
    """Fetch the latest version of a Source's program now."""
    return update_source_program(_source(source_id, Feature.PROGRAM_UPDATES))


@router.get("/sources/{source_id}/cookies", response_model=CookiesAPIRead)
def cookies(source_id: str):
    return CookiesAPIRead(has_cookies=_source(source_id, Feature.COOKIES).has_cookies())


@router.put("/sources/{source_id}/cookies", response_model=CookiesAPIRead)
def save_cookies(source_id: str, body: CookiesAPIUpdate):
    """Store a cookies.txt file that the Source uses for every lookup and download."""
    source = _source(source_id, Feature.COOKIES)
    try:
        source.save_cookies(body.content.encode())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CookiesAPIRead(has_cookies=True)


@router.delete("/sources/{source_id}/cookies", response_model=CookiesAPIRead)
def remove_cookies(source_id: str):
    _source(source_id, Feature.COOKIES).remove_cookies()
    return CookiesAPIRead(has_cookies=False)
