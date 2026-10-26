from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException, Request

from backend.db.model_mapping import create_database_fields
from backend.api.models.show import ShowAPIRead
from backend.api.models.show_local_media_profile import ShowLocalMediaProfileAPICreate, ShowLocalMediaProfileAPIUpdate
from backend.api.models.show_as_bundle import (
    ShowLocalMediaProfileAPIUpsert,
    ShowLocalMediaProfileCreateNew,
    ShowLocalMediaProfileUpdateBySlug,
    ShowAPICreateBundle,
)
from backend.db.models import Season, Show, ShowLocalMediaProfile
from backend.db.models.download_profile import DownloadProfile
from backend.db.models.stream_profile import RssStreamProfile
from backend.utils.feed_urls import build_rss_feed_url
from backend.utils.helpers import generate_stream_profile_token
from backend.types.dailywire_user_info import WlDwMembershipLevel
from backend.types.season_types import SeasonType
from sources import Feature, UnknownSourceError, get_source
from backend.utils.season_ordering import order_initial_seasons, season_type_from_name
from task_manager.events.transactional import queue_event
from task_manager.scheduler.operation_factory import create_operation

from ...rss_stream_profiles.service import ensure_source_can_stream
from ...show_local_media_profiles.service import create_show_local_media_profile, update_show_local_media_profile
from ..events import ShowAdded
from ..operations import ShowIndexOperation


def upsert_show_local_media_profile(
    s: Session,
    mp_input: ShowLocalMediaProfileAPIUpsert,
) -> ShowLocalMediaProfile:
    """Create or update the profile the way the profile endpoints do, indexing values included."""
    fields = mp_input.model_dump(exclude={"op", "slug_selector"})
    if isinstance(mp_input, ShowLocalMediaProfileCreateNew):
        saved = create_show_local_media_profile(s, ShowLocalMediaProfileAPICreate.model_validate(fields))
    elif isinstance(mp_input, ShowLocalMediaProfileUpdateBySlug):
        saved = update_show_local_media_profile(
            s, mp_input.slug_selector, ShowLocalMediaProfileAPIUpdate.model_validate(fields),
        )
    else:
        raise TypeError(f"Unsupported media profile input {type(mp_input).__name__}")
    return s.get(ShowLocalMediaProfile, saved.id)


def create_show_bundle(s: Session, request: Request, payload: ShowAPICreateBundle) -> ShowAPIRead:
    try:
        show_source = get_source(payload.show.source_key)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not show_source.has(Feature.SHOWS):
        raise HTTPException(status_code=422, detail=f"{show_source.name} has no shows")
    show = create_database_fields(Show, payload.show)
    if show_source.has(Feature.EPISODE_LISTS):
        # Indexing puts the episodes in the Source's own seasons, or in a season per
        # upload year. Seasons given here are the Source's, picked for a Download
        # Profile; indexing matches them by slug and numbers them.
        show.membership_level = WlDwMembershipLevel.FREE.value
    s.add(show)

    # The Add Show flow supplies seasons as part of the initial bundle, before the
    # fetch-new-episodes worker runs. Normalize them here so their persistent
    # indices are correct from the moment they are first stored.
    seasons: list[Season] = []
    regular_season_number = 0
    for index, season_in in enumerate(order_initial_seasons(payload.seasons), start=1):
        season = create_database_fields(Season, season_in)
        season_type = season_type_from_name(season_in.name)
        if season_type is SeasonType.NORMAL:
            regular_season_number += 1
            season_number = regular_season_number
        else:
            season_number = 0
        season.index = index
        season.season_type = season_type.value
        season.season_number = season_number
        season.show = show
        s.add(season)
        seasons.append(season)

    local_media_profile: Optional[ShowLocalMediaProfile] = None
    if payload.local_media_profile is not None:
        local_media_profile = upsert_show_local_media_profile(s, payload.local_media_profile)

    if payload.download_profile is not None:
        if local_media_profile is None:
            raise ValueError("A local media profile is required when creating a download profile")

        download_profile = create_database_fields(
            DownloadProfile,
            payload.download_profile,
            exclude_fields={"seasons"},
        )
        selected_slugs = {
            season.slug for season in payload.download_profile.seasons
        }
        download_profile.seasons = [
            season for season in seasons if season.slug in selected_slugs
        ]
        s.add(download_profile)
        download_profile.show = show
        download_profile.local_media_profile = local_media_profile

    if payload.stream_profile is not None:
        ensure_source_can_stream(show, payload.stream_profile.use_dw_stream)
        token = generate_stream_profile_token()
        feed_url = (payload.stream_profile.feed_url or "").strip()
        stream_profile = create_database_fields(
            RssStreamProfile,
            payload.stream_profile,
            exclude_fields={"show_id", "feed_url", "title"},
        )
        normalized_title = payload.stream_profile.title.strip()
        stream_profile.overwrite_show_title = (
            None if normalized_title == show.title else normalized_title
        )
        stream_profile.token = token
        stream_profile.feed_url = (
            feed_url
            or build_rss_feed_url(request, token=token, show_slug=show.slug)
        )
        stream_profile.show = show
        s.add(stream_profile)

    s.flush()
    create_operation(s, ShowIndexOperation(show))
    queue_event(s, "show.added", ShowAdded(show))
    return ShowAPIRead.model_validate(show)
