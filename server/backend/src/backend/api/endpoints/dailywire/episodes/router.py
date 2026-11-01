from fastapi import APIRouter

from backend.api.datetime import api_timezone_payload
from backend.api.endpoints.dailywire.episodes.service import *
from sources.dailywire.api.records import DwEpisodeRecord, DwEpisodeDetailRecord
from backend.security.access import Area, Level
from backend.security.deps import requires_any


router = APIRouter(prefix="/episodes", tags=["DailyWire Episodes"])

@router.get("/by-show-slug/{show_slug}", dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.VIEW))], response_model=list[DwEpisodeRecord])
def episodes_by_show_list(show_slug: str):
    return api_timezone_payload(get_episodes_list_by_show(show_slug))


@router.get("/{episode_slug}", dependencies=[requires_any((Area.ADD_MEDIA, Level.VIEW), (Area.LIBRARY, Level.VIEW))], response_model=DwEpisodeDetailRecord)
def episode_detail(episode_slug: str):
    return api_timezone_payload(get_episode_details(episode_slug))