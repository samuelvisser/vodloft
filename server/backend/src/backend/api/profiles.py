from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.db.models import DownloadProfile, LocalMediaProfile, StreamProfile
from backend.schemas import (
    DownloadProfileCreate,
    DownloadProfileRead,
    LocalMediaProfileCreate,
    LocalMediaProfileRead,
    StreamProfileCreate,
    StreamProfileRead,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _commit(session: Session, obj):
    try:
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="A profile with that name already exists") from exc


@router.get("/local-media", response_model=list[LocalMediaProfileRead])
def list_local_media_profiles(session: Session = Depends(get_session)):
    return list(session.scalars(select(LocalMediaProfile).order_by(LocalMediaProfile.name)))


@router.post("/local-media", response_model=LocalMediaProfileRead, status_code=201)
def create_local_media_profile(payload: LocalMediaProfileCreate, session: Session = Depends(get_session)):
    return _commit(session, LocalMediaProfile(**payload.model_dump(mode="json")))


@router.get("/downloads", response_model=list[DownloadProfileRead])
def list_download_profiles(session: Session = Depends(get_session)):
    return list(session.scalars(select(DownloadProfile).order_by(DownloadProfile.name)))


@router.post("/downloads", response_model=DownloadProfileRead, status_code=201)
def create_download_profile(payload: DownloadProfileCreate, session: Session = Depends(get_session)):
    if session.get(LocalMediaProfile, payload.local_media_profile_id) is None:
        raise HTTPException(status_code=422, detail="Local media profile does not exist")
    return _commit(session, DownloadProfile(**payload.model_dump()))


@router.get("/streams", response_model=list[StreamProfileRead])
def list_stream_profiles(session: Session = Depends(get_session)):
    return list(session.scalars(select(StreamProfile).order_by(StreamProfile.name)))


@router.post("/streams", response_model=StreamProfileRead, status_code=201)
def create_stream_profile(payload: StreamProfileCreate, session: Session = Depends(get_session)):
    return _commit(session, StreamProfile(**payload.model_dump()))
