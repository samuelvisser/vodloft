"""Local accounts and approval of acquisition demand."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import (AcquisitionJob, LibraryRequest, LocalUser, MediaDemand,
    MediaItem, MediaServerTarget, SourceConnection, SourceReference)
from backend.security.permissions import principal, require_connection
from config.security.admin_auth import AdminAuth
from config.security.passwords import hash_password_scrypt

router = APIRouter(prefix="/vodloft", tags=["VodLoft requests and permissions"])


class UserInput(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,79}$")
    passwordHash: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    role: Literal["member", "manager"] = "member"
    enabled: bool = True
    can_subscribe: bool = True
    auto_approve: bool = False
    request_quota: int = Field(default=10, ge=1, le=10000)
    connection_ids: list[int] = Field(default_factory=list)
    target_ids: list[int] = Field(default_factory=list)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    username: str
    role: str
    enabled: bool
    can_subscribe: bool
    auto_approve: bool
    request_quota: int
    connection_ids: list[int]
    target_ids: list[int]


@router.get("/me")
def me(request: Request):
    actor = principal(request)
    return {"key": actor.key, "username": actor.username, "role": actor.role,
        "can_subscribe": actor.can_subscribe, "auto_approve": actor.auto_approve,
        "request_quota": actor.request_quota, "manages_library": actor.manages_library}


def _validate_grants(session, data: UserInput):
    if data.username == "admin":
        raise HTTPException(422, "The administrator name is reserved")
    if any(not session.get(SourceConnection, key) for key in data.connection_ids) or any(
            not session.get(MediaServerTarget, key) for key in data.target_ids):
        raise HTTPException(422, "Select existing Source connections and media servers")


@router.get("/users", response_model=list[UserResponse])
def users():
    with get_session() as session:
        return [UserResponse.model_validate(user) for user in session.scalars(select(LocalUser)).all()]


@router.post("/users", response_model=UserResponse, status_code=201)
def add_user(data: UserInput):
    if not AdminAuth().is_enabled:
        raise HTTPException(409, "Configure the administrator password before enabling multiple accounts")
    if not data.passwordHash:
        raise HTTPException(422, "A password is required for a new local account")
    with get_session() as session:
        _validate_grants(session, data)
        user = LocalUser(key=uuid.uuid4().hex, password_hash=hash_password_scrypt(data.passwordHash),
            **data.model_dump(exclude={"passwordHash"}))
        session.add(user)
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "That username already exists") from exc
        return UserResponse.model_validate(user)


@router.put("/users/{user_key}", response_model=UserResponse)
def update_user(user_key: str, data: UserInput):
    with get_session() as session:
        user = session.get(LocalUser, user_key)
        if not user:
            raise HTTPException(404, "Local account not found")
        _validate_grants(session, data)
        for name, value in data.model_dump(exclude={"passwordHash"}).items():
            setattr(user, name, value)
        if data.passwordHash:
            user.password_hash = hash_password_scrypt(data.passwordHash)
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "That username already exists") from exc
        return UserResponse.model_validate(user)


class RequestInput(BaseModel):
    profile_id: int
    reference_id: int | None = None


class RequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_key: str
    item_id: int
    profile_id: int
    state: str
    job_id: int | None
    reason: str | None
    created_at: datetime


def _approve(request_id: int) -> RequestResponse:
    from backend.api.endpoints.vodloft.router import queue_download
    with get_session() as session:
        demand = session.get(LibraryRequest, request_id)
        if not demand or demand.state not in {"pending", "approved"}:
            raise HTTPException(409, "This request cannot be approved")
        item_id, profile_id, reference_id = demand.item_id, demand.profile_id, demand.reference_id
        owner = session.get(LocalUser, demand.user_key) if demand.user_key != "admin" else None
        reference = session.get(SourceReference, reference_id)
        if demand.user_key != "admin" and (not owner or not owner.enabled or not reference or (
                reference.connection_id is not None and reference.connection_id not in owner.connection_ids)):
            raise HTTPException(403, "The requesting account no longer has Source access")
    job_id, state, _ = queue_download(item_id, profile_id, reference_id=reference_id,
                                     request_id=request_id)
    if state == "suppressed":
        raise HTTPException(409, "This representation was intentionally removed. An administrator must resume acquisition first.")
    with get_session() as session:
        demand = session.get(LibraryRequest, request_id)
        demand.job_id = job_id
        demand.state = "fulfilled" if state == "available" else "approved"
        demand.reason = None
        session.commit()
        return RequestResponse.model_validate(demand)


@router.post("/library/{item_id}/requests", response_model=RequestResponse, status_code=201)
def request_media(item_id: int, data: RequestInput, request: Request, background: BackgroundTasks):
    from backend.api.endpoints.vodloft.router import _reference_for, _run_download
    actor = principal(request)
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        profile = session.get(DomainLocalMediaProfile, data.profile_id)
        if not item or item.kind == "collection" or not profile or profile.deleted or profile.impairment or not profile.enabled or (
                profile.domain_id != item.domain_id or item.kind not in profile.applicable_kinds):
            raise HTTPException(422, "Select a playable item and compatible enabled Local Media Profile")
        reference = _reference_for(session, item_id, reference_id=data.reference_id)
        if not reference:
            raise HTTPException(409, "Select one available Source account reference")
        require_connection(request, reference.connection_id)
        key = f"{actor.key}:{item_id}:{data.profile_id}"
        existing = session.scalar(select(LibraryRequest).where(LibraryRequest.active_key == key))
        if existing:
            return RequestResponse.model_validate(existing)
        active = session.scalar(select(func.count()).select_from(LibraryRequest).where(
            LibraryRequest.user_key == actor.key, LibraryRequest.state.in_(["pending", "approved"])))
        if active >= actor.request_quota:
            raise HTTPException(429, "The local account's open request quota is reached")
        demand = LibraryRequest(user_key=actor.key, item_id=item_id, profile_id=data.profile_id,
            reference_id=reference.id, state="pending", active_key=key)
        session.add(demand)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(select(LibraryRequest).where(LibraryRequest.active_key == key))
            if not existing:
                raise
            return RequestResponse.model_validate(existing)
        request_id = demand.id
        pending_response = RequestResponse.model_validate(demand)
    if actor.auto_approve:
        result = _approve(request_id)
        if result.job_id:
            background.add_task(_run_download, result.job_id)
        return result
    return pending_response


@router.get("/requests", response_model=list[RequestResponse])
def requests(request: Request):
    actor = principal(request)
    with get_session() as session:
        query = select(LibraryRequest).order_by(LibraryRequest.created_at.desc()).limit(200)
        if not actor.manages_library:
            query = query.where(LibraryRequest.user_key == actor.key)
        result = session.scalars(query).all()
        for demand in result:
            job = session.get(AcquisitionJob, demand.job_id) if demand.job_id else None
            if demand.state == "approved" and job:
                if job.state == "available":
                    demand.state, demand.reason = "fulfilled", None
                elif job.state in {"failed", "canceled"}:
                    demand.state = "failed"
                    demand.reason = job.error or "Acquisition was canceled"
                    demand.active_key = None
        session.commit()
        return [RequestResponse.model_validate(demand) for demand in result]


@router.post("/requests/{request_id}/approve", response_model=RequestResponse)
def approve_request(request_id: int, background: BackgroundTasks):
    from backend.api.endpoints.vodloft.router import _run_download
    result = _approve(request_id)
    if result.job_id:
        background.add_task(_run_download, result.job_id)
    return result


class RejectionInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/requests/{request_id}/reject", response_model=RequestResponse)
def reject_request(request_id: int, data: RejectionInput):
    with get_session() as session:
        demand = session.get(LibraryRequest, request_id)
        if not demand or demand.state != "pending":
            raise HTTPException(409, "Only a pending request can be rejected")
        demand.state, demand.reason, demand.active_key = "rejected", data.reason, None
        session.commit()
        return RequestResponse.model_validate(demand)


@router.delete("/requests/{request_id}", status_code=204)
def withdraw_request(request_id: int, request: Request):
    from backend.source_manager.gateway import cancel_running_job
    actor = principal(request)
    with get_session() as session:
        demand = session.get(LibraryRequest, request_id)
        if not demand or not actor.manages_library and demand.user_key != actor.key:
            raise HTTPException(404, "Request not found")
        demand.state, demand.active_key = "canceled", None
        session.execute(delete(MediaDemand).where(MediaDemand.owner_kind == "request", MediaDemand.owner_id == request_id))
        session.flush()
        if demand.job_id and not session.scalar(select(MediaDemand.id).where(
                MediaDemand.item_id == demand.item_id, MediaDemand.profile_id == demand.profile_id)):
            job = session.get(AcquisitionJob, demand.job_id)
            if job and job.active_key:
                job.cancel_requested = True
                cancel_running_job(job.id)
        session.commit()
