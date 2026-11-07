from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException, Request

from backend.db.model_mapping import create_database_fields
from backend.services.episode_filters import set_profile_filters
from backend.api.models.collection import CollectionAPIRead
from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate, CollectionLocalMediaProfileAPIUpdate
from backend.api.models.collection_as_bundle import (
    CollectionLocalMediaProfileAPIUpsert,
    CollectionLocalMediaProfileCreateNew,
    CollectionLocalMediaProfileUpdateBySlug,
    CollectionAPICreateBundle,
)
from backend.db.models import Season, Collection, CollectionLocalMediaProfile
from backend.db.models.download_profile import DownloadProfile
from backend.db.models.stream_profile import RssStreamProfile
from backend.services.adoption import AdoptionError
from backend.services.existing_files import ExistingFilesError, request_scan
from backend.utils.feed_urls import build_rss_feed_url, request_base_url
from backend.utils.helpers import generate_stream_profile_token
from task_manager.scheduler.requester import current_requester
from backend.utils.season_ordering import number_initial_seasons

from ...rss_stream_profiles.service import ensure_site_can_stream
from ...collection_local_media_profiles.service import create_collection_local_media_profile, update_collection_local_media_profile
from backend.services.collections import add_collection, index_new_collection


def upsert_collection_local_media_profile(
    s: Session,
    mp_input: CollectionLocalMediaProfileAPIUpsert,
) -> CollectionLocalMediaProfile:
    """Create or update the profile the way the profile endpoints do, indexing values included."""
    fields = mp_input.model_dump(exclude={"op", "slug_selector"})
    if isinstance(mp_input, CollectionLocalMediaProfileCreateNew):
        saved = create_collection_local_media_profile(s, CollectionLocalMediaProfileAPICreate.model_validate(fields))
    elif isinstance(mp_input, CollectionLocalMediaProfileUpdateBySlug):
        saved = update_collection_local_media_profile(
            s, mp_input.slug_selector, CollectionLocalMediaProfileAPIUpdate.model_validate(fields),
        )
    else:
        raise TypeError(f"Unsupported media profile input {type(mp_input).__name__}")
    return s.get(CollectionLocalMediaProfile, saved.id)


def create_collection_bundle(
    s: Session, request: Request, payload: CollectionAPICreateBundle, *, added_by_id: int | None = None,
) -> CollectionAPIRead:
    collection = create_database_fields(Collection, payload.collection)
    add_collection(s, collection, added_by_id=added_by_id)

    # The Add Show flow supplies seasons as part of the initial bundle, before the
    # fetch-new-episodes worker runs. Normalize them here so their persistent
    # indices are correct from the moment they are first stored.
    seasons: list[Season] = []
    for season_in, index, season_type, season_number in number_initial_seasons(payload.seasons):
        season = create_database_fields(Season, season_in)
        season.index = index
        season.season_type = season_type.value
        season.season_number = season_number
        season.collection = collection
        s.add(season)
        seasons.append(season)

    local_media_profile: Optional[CollectionLocalMediaProfile] = None
    if payload.local_media_profile is not None:
        local_media_profile = upsert_collection_local_media_profile(s, payload.local_media_profile)

    download_profile: Optional[DownloadProfile] = None
    if payload.download_profile is not None:
        if local_media_profile is None:
            raise ValueError("A local media profile is required when creating a download profile")

        download_profile = create_database_fields(
            DownloadProfile,
            payload.download_profile,
            exclude_fields={"filters"},
        )
        # Season filters name seasons by slug, so they work before indexing numbers the seasons.
        set_profile_filters(download_profile, payload.download_profile.filters)
        s.add(download_profile)
        download_profile.collection = collection
        download_profile.local_media_profile = local_media_profile

    if payload.stream_profile is not None:
        ensure_site_can_stream(
            collection, use_source_stream=payload.stream_profile.use_source_stream,
            stream_live_episodes=payload.stream_profile.stream_live_episodes,
            preferred_format=payload.stream_profile.preferred_format,
            video_output_mode=payload.stream_profile.video_output_mode,
        )
        token = generate_stream_profile_token()
        feed_url = (payload.stream_profile.feed_url or "").strip()
        stream_profile = create_database_fields(
            RssStreamProfile,
            payload.stream_profile,
            exclude_fields={"collection_id", "feed_url", "title"},
        )
        normalized_title = payload.stream_profile.title.strip()
        stream_profile.overwrite_collection_title = (
            None if normalized_title == collection.title else normalized_title
        )
        stream_profile.token = token
        stream_profile.feed_url = (
            feed_url
            or build_rss_feed_url(request_base_url(request), token=token, collection_slug=collection.slug)
        )
        stream_profile.collection = collection
        stream_profile.owner_user_id = current_requester.get()
        s.add(stream_profile)

    s.flush()
    if payload.existing_files is not None:
        if local_media_profile is None:
            raise HTTPException(status_code=422, detail="Matching existing files needs a Local Media Profile")
        try:
            request_scan(
                s, collection, local_media_profile,
                folder=payload.existing_files.folder, template=payload.existing_files.template,
                hold=[download_profile] if download_profile is not None else [], wait_for_index=True,
            )
        except (ExistingFilesError, AdoptionError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    index_new_collection(s, collection)
    return CollectionAPIRead.model_validate(collection)
