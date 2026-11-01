from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.api.datetime import api_timezone_payload
from sources.dailywire.api.records import (
    DwCatalogMoviePageRecord,
    DwCatalogRecord,
    DwCatalogShowPageRecord,
)

from .service import get_catalog, get_catalog_movies, get_catalog_shows
from backend.security.access import Area, Level
from backend.security.deps import requires

router = APIRouter(prefix="/catalog", tags=["DailyWire Catalog"])


@router.get("/shows", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=DwCatalogShowPageRecord)
def catalog_shows(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=60),
    search: str | None = None,
    grouping: Literal['host', 'alphabetical'] = 'host',
):
    try:
        return api_timezone_payload(
            get_catalog_shows(offset=offset, limit=limit, search=search, grouping=grouping)
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/movies", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=DwCatalogMoviePageRecord)
def catalog_movies(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=60),
    search: str | None = None,
):
    try:
        return api_timezone_payload(get_catalog_movies(offset=offset, limit=limit, search=search))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("", dependencies=[requires(Area.ADD_MEDIA, Level.VIEW)], response_model=DwCatalogRecord)
def catalog_detail():
    try:
        return api_timezone_payload(get_catalog())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
