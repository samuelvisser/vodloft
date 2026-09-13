from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.db import get_session
from backend.schemas.settings import AuthStatusRead, LoginRequest, PasswordChangeRequest, SetupRequest
from backend.security import (
    SESSION_COOKIE,
    authenticated,
    create_session_token,
    ensure_application_settings,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


@router.get("/status", response_model=AuthStatusRead)
def auth_status(request: Request, session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    return AuthStatusRead(
        auth_enabled=settings.auth_enabled,
        setup_required=settings.admin_password_hash is None,
        authenticated=authenticated(request.cookies.get(SESSION_COOKIE), settings),
        username=settings.admin_username,
        onboarding_completed=settings.onboarding_completed,
    )


@router.post("/setup", response_model=AuthStatusRead)
def setup_auth(payload: SetupRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    if settings.admin_password_hash:
        raise HTTPException(status_code=409, detail="Administrator authentication is already configured")
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings.admin_username = payload.username.strip() or "admin"
    settings.admin_password_hash = password_hash
    settings.auth_enabled = True
    settings.onboarding_completed = True
    session.commit()
    token = create_session_token(settings.admin_username, settings.session_secret)
    _set_cookie(response, token, request)
    return AuthStatusRead(
        auth_enabled=True,
        setup_required=False,
        authenticated=True,
        username=settings.admin_username,
        onboarding_completed=True,
    )


@router.post("/login", response_model=AuthStatusRead)
def login(payload: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    if not settings.admin_password_hash:
        raise HTTPException(status_code=409, detail="Administrator authentication has not been configured")
    if payload.username != settings.admin_username or not verify_password(payload.password, settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session_token(settings.admin_username, settings.session_secret)
    _set_cookie(response, token, request)
    return AuthStatusRead(
        auth_enabled=settings.auth_enabled,
        setup_required=False,
        authenticated=True,
        username=settings.admin_username,
        onboarding_completed=settings.onboarding_completed,
    )


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.post("/password", status_code=204)
def change_password(payload: PasswordChangeRequest, request: Request, session: Session = Depends(get_session)):
    settings = ensure_application_settings(session)
    if settings.admin_password_hash:
        if not authenticated(request.cookies.get(SESSION_COOKIE), settings):
            raise HTTPException(status_code=401, detail="Authentication required")
        if not payload.current_password or not verify_password(payload.current_password, settings.admin_password_hash):
            raise HTTPException(status_code=422, detail="Current password is incorrect")
    try:
        settings.admin_password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings.auth_enabled = True
    settings.onboarding_completed = True
    session.commit()
    return Response(status_code=204)
