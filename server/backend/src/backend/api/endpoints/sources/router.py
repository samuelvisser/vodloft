from fastapi import APIRouter, HTTPException, Query

from backend.api.models.source import (
    DownloadOptionsAPIRead, SiteOptionsAPIRead, YtdlpOptionLineAPIRead, YtdlpOptionsAPIRead, YtdlpOptionsAPIUpdate, YtdlpOptionsCheckAPIRequest,
    ApiKeyAPIUpdate, ApiStatusAPIRead, CookiesAPIRead, EpisodeTagAPIRead, PublishStatusLabelAPIRead, SourceProblemAPIRead, CookiesAPIUpdate, ProgramStatusAPIRead, ResolveAPIRequest, ResolvedLinkAPIRead, SearchResultsAPIRead,
    CollectionDetailsAPIRead, SourceAPIRead, SourceSiteAPIRead, SourceSiteAPIUpdate,
)
from backend.app import db_session
from sources import ApiKeyRejected, Feature, Source, UnknownSourceError, get_source, site_for
from sources.ytdlp_options import check_ytdlp_options
from backend.services.source_options import save_ytdlp_source_options, ytdlp_source_options

from .service import (
    LinkNotRecognisedError, SourceFeatureMissingError, UnknownSiteError, get_api_status, get_program_status,
    list_source_problems, list_source_sites,
    list_sources, lookup_show_details, resolve_link, search_source, set_site_preference, source_with,
    update_source_program,
)
from backend.security.access import Access, Area, Level
from backend.security.deps import requires, requires_any, signed_in


router = APIRouter(tags=["Sources"])


def _source(source_id: str, feature: Feature) -> Source:
    try:
        return source_with(source_id, feature)
    except SourceFeatureMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sources", dependencies=[signed_in()], response_model=list[SourceAPIRead])
def source_list():
    """List every Source with the Features it supports."""
    return list_sources()


@router.get("/sources/problems", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=list[SourceProblemAPIRead])
def source_problems():
    """What the user should fix about any Source, such as an API key that stopped working."""
    return list_source_problems()


@router.get("/sources/sites", dependencies=[signed_in()], response_model=list[SourceSiteAPIRead])
def source_sites():
    """Every Site a Source is made for, with the Sources that can handle its links."""
    with db_session() as s:
        return list_source_sites(s)


@router.put("/sources/sites/{key}", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=SourceSiteAPIRead)
def update_source_site(key: str, body: SourceSiteAPIUpdate):
    """Choose the Source to ask first for links on a Site."""
    with db_session() as s:
        try:
            result = set_site_preference(s, key, body.preferred_source_key)
        except UnknownSiteError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        s.commit()
        return result


@router.post("/resolve", dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.QUICK_DOWNLOADS, Level.VIEW))], response_model=ResolvedLinkAPIRead)
def resolve(body: ResolveAPIRequest, access: Access = signed_in()):
    """Find the Source that recognises a link, and what the link points to."""
    with db_session() as s:
        try:
            return resolve_link(s, access, body.url, body.source_key)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sources/{source_id}/episode-tags", dependencies=[requires_any((Area.LIBRARY, Level.VIEW), (Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=list[EpisodeTagAPIRead])
def episode_tags(source_id: str, url: str | None = Query(default=None, max_length=2048)):
    """The tags a Source gives episodes, such as Video, Short and Livestream, for the collection at ``url`` or for any collection."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [EpisodeTagAPIRead.model_validate(tag) for tag in source.episode_tags_for(url)]


@router.get("/sources/{source_id}/publish-statuses", dependencies=[signed_in()], response_model=list[PublishStatusLabelAPIRead])
def publish_statuses(source_id: str):
    """What the Source calls each publish status, such as Scheduled or Published (still contains countdown)."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PublishStatusLabelAPIRead.model_validate(label) for label in source.publish_status_labels]


@router.get("/sources/{source_id}/site-options", dependencies=[requires_any((Area.LIBRARY, Level.VIEW), (Area.DOWNLOAD_PROFILES, Level.VIEW), (Area.STREAM_PROFILES, Level.VIEW), (Area.ADD_MEDIA, Level.VIEW))], response_model=SiteOptionsAPIRead)
def site_options(source_id: str, url: str = Query(min_length=1, max_length=2048)):
    """Choices only some sites of a Source offer, such as YouTube's auto-generated subtitles, for the collection at ``url``."""
    try:
        source = get_source(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    site = site_for(url, source.id)
    return SiteOptionsAPIRead(
        auto_subtitles=source.auto_subtitles_for(url), sponsorblock=source.sponsorblock_for(url),
        upgrade_checks=source.has(Feature.UPGRADE_CHECKS), site_name=site.name,
        stream_methods=site.stream_methods,
            stream_video_heights=site.stream_video_heights, stream_proxy_choice=site.stream_proxy_choice,
            downloads=DownloadOptionsAPIRead.model_validate(site.downloads),
    )


@router.post("/sources/ytdlp-options/check", dependencies=[requires_any((Area.SOURCES, Level.MANAGE), (Area.LIBRARY, Level.MANAGE))], response_model=list[YtdlpOptionLineAPIRead])
def ytdlp_options_check(body: YtdlpOptionsCheckAPIRequest):
    """Check your own yt-dlp options line by line with yt-dlp's parser, before they are saved."""
    return [YtdlpOptionLineAPIRead.model_validate(line) for line in check_ytdlp_options(body.text)]


@router.get("/sources/{source_id}/ytdlp-options", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=YtdlpOptionsAPIRead)
def ytdlp_options(source_id: str):
    """The yt-dlp options the Source gives every download."""
    _source(source_id, Feature.YTDLP_DOWNLOADS)
    with db_session() as s:
        return YtdlpOptionsAPIRead(text=ytdlp_source_options(s))


@router.put("/sources/{source_id}/ytdlp-options", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=YtdlpOptionsAPIRead)
def save_ytdlp_options(source_id: str, body: YtdlpOptionsAPIUpdate):
    _source(source_id, Feature.YTDLP_DOWNLOADS)
    with db_session() as s:
        text = save_ytdlp_source_options(s, body.text)
        s.commit()
        return YtdlpOptionsAPIRead(text=text)


@router.get("/sources/{source_id}/collection", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=CollectionDetailsAPIRead)
def collection_details(source_id: str, url: str = Query(min_length=1, max_length=2048), access: Access = signed_in()):
    """Look up a collection to add, at a Source that lists its episodes."""
    return lookup_show_details(access, _source(source_id, Feature.EPISODE_LISTS), url)


@router.get("/sources/{source_id}/search", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=SearchResultsAPIRead)
def search(source_id: str, q: str = Query(min_length=1, max_length=200), access: Access = signed_in()):
    """Find collections and videos at a Source by name."""
    return search_source(access, _source(source_id, Feature.SEARCH), q)


@router.get("/sources/{source_id}/program", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ProgramStatusAPIRead)
def program_status(source_id: str):
    """The program a Source runs, such as yt-dlp, and when it was last updated."""
    return get_program_status(_source(source_id, Feature.PROGRAM_UPDATES))


@router.post("/sources/{source_id}/program/update", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ProgramStatusAPIRead)
def update_program(source_id: str):
    """Fetch the latest version of a Source's program now."""
    return update_source_program(_source(source_id, Feature.PROGRAM_UPDATES))


@router.get("/sources/{source_id}/cookies", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=CookiesAPIRead)
def cookies(source_id: str):
    return _cookies(_source(source_id, Feature.COOKIES))


@router.put("/sources/{source_id}/cookies", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=CookiesAPIRead)
def save_cookies(source_id: str, body: CookiesAPIUpdate):
    """Store a cookies.txt file that the Source uses for every lookup and download."""
    source = _source(source_id, Feature.COOKIES)
    try:
        source.save_cookies(body.content.encode())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _cookies(source)


@router.delete("/sources/{source_id}/cookies", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=CookiesAPIRead)
def remove_cookies(source_id: str):
    source = _source(source_id, Feature.COOKIES)
    source.remove_cookies()
    return _cookies(source)


def _cookies(source: Source) -> CookiesAPIRead:
    has_cookies = source.has_cookies()
    return CookiesAPIRead(has_cookies=has_cookies, status=source.cookies_status() if has_cookies else None)


def _api_key_rejected(exc: ApiKeyRejected) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(exc), "fixUrl": exc.fix_url})


@router.get("/sources/{source_id}/api", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def api_status(source_id: str):
    """The Source's API key and how much of today's quota it spent."""
    source = _source(source_id, Feature.API_KEY)
    with db_session() as s:
        return get_api_status(s, source)


@router.put("/sources/{source_id}/api/key", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def save_api_key(source_id: str, body: ApiKeyAPIUpdate):
    """Test an API key with one call, and store it when the service accepts it."""
    source = _source(source_id, Feature.API_KEY)
    try:
        source.save_api_key(body.key)
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.post("/sources/{source_id}/api/key/test", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def test_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    try:
        source.test_api_key()
    except ApiKeyRejected as exc:
        raise _api_key_rejected(exc) from exc
    with db_session() as s:
        return get_api_status(s, source)


@router.delete("/sources/{source_id}/api/key", dependencies=[requires(Area.SOURCES, Level.MANAGE)], response_model=ApiStatusAPIRead)
def remove_api_key(source_id: str):
    source = _source(source_id, Feature.API_KEY)
    source.remove_api_key()
    with db_session() as s:
        return get_api_status(s, source)
