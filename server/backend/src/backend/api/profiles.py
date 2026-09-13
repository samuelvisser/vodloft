from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.db.models import Collection, DownloadProfile, LocalMediaProfile, StreamProfile
from backend.schemas import (
    DownloadProfileCreate,
    DownloadProfileRead,
    DownloadProfileUpdate,
    LocalMediaProfileCreate,
    LocalMediaProfileRead,
    LocalMediaProfileUpdate,
    StreamProfileCreate,
    StreamProfileRead,
    StreamProfileUpdate,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "profile"


def _available_slug(session: Session, name: str, *, exclude_id: int | None = None) -> str:
    base = _slugify(name)
    candidate = base
    index = 2
    while True:
        statement = select(LocalMediaProfile.id).where(LocalMediaProfile.slug == candidate)
        if exclude_id is not None:
            statement = statement.where(LocalMediaProfile.id != exclude_id)
        if session.scalar(statement) is None:
            return candidate
        candidate = f"{base}-{index}"
        index += 1


def _commit(session: Session, obj, *, conflict: str):
    try:
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc


def _delete(session: Session, obj) -> Response:
    try:
        session.delete(obj)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Profile is still in use") from exc
    return Response(status_code=204)


@router.get("/local-media", response_model=list[LocalMediaProfileRead])
def list_local_media_profiles(scope: str | None = None, session: Session = Depends(get_session)):
    statement = select(LocalMediaProfile)
    if scope is not None:
        statement = statement.where(LocalMediaProfile.scope == scope)
    return list(session.scalars(statement.order_by(LocalMediaProfile.name)))


@router.post("/local-media", response_model=LocalMediaProfileRead, status_code=201)
def create_local_media_profile(payload: LocalMediaProfileCreate, session: Session = Depends(get_session)):
    values = payload.model_dump(mode="json")
    profile = LocalMediaProfile(slug=_available_slug(session, payload.name), **values)
    return _commit(session, profile, conflict="A local media profile with that name already exists")


@router.put("/local-media/{profile_id}", response_model=LocalMediaProfileRead)
def update_local_media_profile(
    profile_id: int,
    payload: LocalMediaProfileUpdate,
    session: Session = Depends(get_session),
):
    profile = session.get(LocalMediaProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Local media profile not found")
    changes = payload.model_dump(exclude_unset=True, mode="json")
    future_scope = changes.get("scope", profile.scope)
    future_kind = changes.get("media_kind", profile.media_kind)
    if future_scope == "video" and future_kind != "video":
        raise HTTPException(status_code=422, detail="Standalone-video local media profiles must use video media kind")
    if "name" in changes and changes["name"] != profile.name:
        profile.slug = _available_slug(session, changes["name"], exclude_id=profile.id)
    for key, value in changes.items():
        setattr(profile, key, value)
    return _commit(session, profile, conflict="A local media profile with that name already exists")


@router.delete("/local-media/{profile_id}", status_code=204)
def delete_local_media_profile(profile_id: int, session: Session = Depends(get_session)):
    profile = session.get(LocalMediaProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Local media profile not found")
    return _delete(session, profile)


@router.get("/downloads", response_model=list[DownloadProfileRead])
def list_download_profiles(collection_id: int | None = None, session: Session = Depends(get_session)):
    statement = select(DownloadProfile)
    if collection_id is not None:
        statement = statement.where(DownloadProfile.collection_id == collection_id)
    return list(session.scalars(statement.order_by(DownloadProfile.name)))


@router.post("/downloads", response_model=DownloadProfileRead, status_code=201)
def create_download_profile(payload: DownloadProfileCreate, session: Session = Depends(get_session)):
    if session.get(Collection, payload.collection_id) is None:
        raise HTTPException(status_code=422, detail="Collection does not exist")
    local = session.get(LocalMediaProfile, payload.local_media_profile_id)
    if local is None:
        raise HTTPException(status_code=422, detail="Local media profile does not exist")
    if local.scope != "collection":
        raise HTTPException(status_code=422, detail="Download profiles require a collection local media profile")
    return _commit(
        session,
        DownloadProfile(**payload.model_dump()),
        conflict="A download profile with that name or local media profile already exists for this collection",
    )


@router.put("/downloads/{profile_id}", response_model=DownloadProfileRead)
def update_download_profile(
    profile_id: int,
    payload: DownloadProfileUpdate,
    session: Session = Depends(get_session),
):
    profile = session.get(DownloadProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Download profile not found")
    changes = payload.model_dump(exclude_unset=True)
    if "local_media_profile_id" in changes:
        local = session.get(LocalMediaProfile, changes["local_media_profile_id"])
        if local is None or local.scope != "collection":
            raise HTTPException(status_code=422, detail="Download profiles require a collection local media profile")
    for key, value in changes.items():
        setattr(profile, key, value)
    return _commit(session, profile, conflict="Download profile conflicts with an existing profile")


@router.delete("/downloads/{profile_id}", status_code=204)
def delete_download_profile(profile_id: int, session: Session = Depends(get_session)):
    profile = session.get(DownloadProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Download profile not found")
    return _delete(session, profile)


@router.get("/streams", response_model=list[StreamProfileRead])
def list_stream_profiles(collection_id: int | None = None, session: Session = Depends(get_session)):
    statement = select(StreamProfile)
    if collection_id is not None:
        statement = statement.where(StreamProfile.collection_id == collection_id)
    return list(session.scalars(statement.order_by(StreamProfile.name)))


@router.post("/streams", response_model=StreamProfileRead, status_code=201)
def create_stream_profile(payload: StreamProfileCreate, session: Session = Depends(get_session)):
    if session.get(Collection, payload.collection_id) is None:
        raise HTTPException(status_code=422, detail="Collection does not exist")
    return _commit(
        session,
        StreamProfile(**payload.model_dump()),
        conflict="A stream profile with that name already exists",
    )


@router.put("/streams/{profile_id}", response_model=StreamProfileRead)
def update_stream_profile(
    profile_id: int,
    payload: StreamProfileUpdate,
    session: Session = Depends(get_session),
):
    profile = session.get(StreamProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    return _commit(session, profile, conflict="A stream profile with that name already exists")


@router.delete("/streams/{profile_id}", status_code=204)
def delete_stream_profile(profile_id: int, session: Session = Depends(get_session)):
    profile = session.get(StreamProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stream profile not found")
    return _delete(session, profile)
