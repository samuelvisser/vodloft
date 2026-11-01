from fastapi import APIRouter, HTTPException

from backend.api.datetime import api_timezone_payload
from sources.dailywire.api.records import DwMovieRecord

from .service import get_movie
from backend.security.access import Area, Level
from backend.security.deps import requires_any

router = APIRouter(prefix="/movies", tags=["DailyWire Movies"])


@router.get("/{movie_slug}", dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.VIEW))], response_model=DwMovieRecord)
def movie_detail(movie_slug: str):
    try:
        return api_timezone_payload(get_movie(movie_slug))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
