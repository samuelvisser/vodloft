from fastapi import APIRouter, HTTPException, Query

from backend.api.models.source import (
    ApiKeyAPIUpdate, ApiStatusAPIRead, CookiesAPIRead, EpisodeTagAPIRead, SourceProblemAPIRead, CookiesAPIUpdate, ProgramStatusAPIRead, ResolveAPIRequest, ResolvedLinkAPIRead, SearchResultsAPIRead,
    ShowDetailsAPIRead, SourceAPIRead, SourceDomainAPIRead, SourceDomainAPIUpdate,
)
from backend.app import db_session
from sources import ApiKeyRejected, Feature, Source, UnknownSourceError, get_source

from .service import (
    LinkNotRecognisedError, SourceFeatureMissingError, UnknownDomainError, get_api_status, get_program_status,
    list_source_problems, list_source_domains,
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


@router.get("/sources/problems", response_model=list[SourceProblemAPIRead])
def source_problems():
    """What the user should fix about any Source, such as an API key that stopped working."""
    return list_source_problems()


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


@router.get("/sources/{source_id}/episode-tags", response_model=list[EpisodeTagAPIRead])
def episode_tags(source_id: str, url: str | None = Query(default=None, max_length=2048)):
    """The tags a Source gives episodes, such as Video, Short and Livestream, for the show at ``url`` or for any show."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [EpisodeTagAPIRead.model_validate(tag) for tag in source.episode_tags_for(url)]


@router.get("/sources/{source_id}/show", response_model=ShowDetailsAPIRead)
def show_details(source_id: str, url: str = Query(min_length=1, max_length=2048)):
    """Look up a show to add, at a Source that lists its episodes."""
    return lookup_show_details(_source(source_id, Feature.EPISODE_LISTS), url)


@router.get("/sources/{source_id}/search", response_model=SearchResultsAPIRead)
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


def _api_key_rejected(exc: ApiKeyRejected) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(exc), "fixUrl": exc.fix_url})


@router.get("/sources/{source_id}/api", response_model=ApiStatusAPIRead)
def api_status(source_id: str):
    """The Source's API key and how much of today's quota it spent."""
    source = _source(source_id, Feature.API_KEY)
    with db_session() as s:
        return get_api_status(s, source)


@router.put("/sources/{source_id}/api/key", response_model=ApiStatusAPIRead)
def save_api_key(source_id: str, body: ApiKeyAPIUpdate):
    """Test an API key with one call, and store it when the service accepts it."""
    source = _source(source_id, Feature.API_KEY)
    try:
        source.save_api_key(body.key)
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.post("/sources/{source_id}/api/key/test", response_model=ApiStatusAPIRead)
def test_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    try:
        source.test_api_key()
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.delete("/sources/{source_id}/api/key", response_model=ApiStatusAPIRead)
def remove_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    source.remove_api_key()
    with db_session() as s:
        return get_api_status(s, source)
