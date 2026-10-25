from fastapi import APIRouter, HTTPException

from backend.api.models.source import ResolveAPIRequest, ResolvedLinkAPIRead, SourceAPIRead
from backend.app import db_session

from .service import LinkNotRecognisedError, SourceLookupError, list_sources, resolve_link


router = APIRouter(tags=["Sources"])


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
