import logging

from fastapi import APIRouter, HTTPException, Query

from backend.api.models.source import (
    CookiesAPIRead, CookiesAPIUpdate, ProgramStatusAPIRead, ResolveAPIRequest, ResolvedLinkAPIRead, ShowDetailsAPIRead,
    SourceAPIRead,
)
from backend.app import db_session
from backend.utils.helpers import slugify
from config.network import is_no_internet_error
from sources import Feature, Source

from .service import (
    LinkNotRecognisedError, SourceFeatureMissingError, SourceLookupError, list_sources, resolve_link, source_with,
    to_program_read,
)


logger = logging.getLogger(__name__)

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


@router.post("/resolve", response_model=ResolvedLinkAPIRead)
def resolve(body: ResolveAPIRequest):
    """Find the Source that recognises a link, and what the link points to."""
    with db_session() as s:
        try:
            return resolve_link(s, body.url)
        except LinkNotRecognisedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SourceLookupError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sources/{source_id}/show", response_model=ShowDetailsAPIRead)
def show_details(source_id: str, url: str = Query(min_length=1, max_length=2048)):
    """Look up a show to add, at a Source that lists its episodes."""
    source = _source(source_id, Feature.EPISODE_LISTS)
    try:
        details = source.show_details(url)
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        raise HTTPException(status_code=502, detail=f"{source.name} could not look up this show: {exc}") from exc
    author = details.author_name or details.title
    return ShowDetailsAPIRead(
        source_key=source.id, slug=details.slug, title=details.title, description=details.description,
        sharing_url=details.url, author_name=author, author_slug=slugify(author) or details.slug,
        thumbnail_landscape_path=details.image_url,
    )


@router.get("/sources/{source_id}/program", response_model=ProgramStatusAPIRead)
def program_status(source_id: str):
    """The program a Source runs, such as yt-dlp, and when it was last updated."""
    return to_program_read(_source(source_id, Feature.PROGRAM_UPDATES).program_status())


@router.post("/sources/{source_id}/program/update", response_model=ProgramStatusAPIRead)
def update_program(source_id: str):
    """Fetch the latest version of a Source's program now."""
    source = _source(source_id, Feature.PROGRAM_UPDATES)
    try:
        return to_program_read(source.update_program())
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.warning("Could not update %s: %s", source.name, exc)
        raise HTTPException(status_code=502, detail=f"Could not update {source.name}: {exc}") from exc


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
