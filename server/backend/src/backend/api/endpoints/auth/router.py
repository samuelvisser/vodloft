from __future__ import annotations

from fastapi import APIRouter, Request, Response, status, HTTPException
from fastapi.concurrency import run_in_threadpool

from backend.api.models.auth import AuthMeRead, AuthResponse, LoginInput, PasswordChangeInput
from backend.app import db_session
from backend.db.core import run_write_transaction
from backend.db.models import User
from backend.security.auth import (
    clear_session_cookie,
    request_access,
    resolve_access,
    set_session_cookie,
    verify_admin_password_hash,
)
from backend.security.login_throttle import login_throttle
from backend.services import users

from .service import describe_access
from backend.security.deps import signed_in

router = APIRouter(tags=["auth"], prefix="/auth")


def _login_error(field: str, message: str) -> HTTPException:
    # A server error in FastAPI format with field-level mapping
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=[{"loc": ["body", field], "msg": message, "type": "value_error"}],
    )


@router.get("/status", response_model=AuthResponse)
async def auth_status(request: Request) -> AuthResponse:
    if await run_in_threadpool(resolve_access, request) is not None:
        return AuthResponse(authenticated=True)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def _sign_in(data: LoginInput, response: Response, address: str | None) -> None:
    username = (data.username or "").strip()
    wait = login_throttle.wait_seconds(username, address)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-ins. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    with db_session() as s:
        accounts = users.accounts_enabled(s)
        user = users.authenticate(s, username, data.passwordHash) if accounts and username else None
        if accounts and username and user is None:
            login_throttle.record_failure(username, address)
            raise _login_error("password", "Incorrect username or password")
        if user is not None:
            user_id, session_version = user.id, user.session_version
        elif accounts and users.enabled_administrators(s):
            raise _login_error("username", "Enter your username")

    if user is not None:
        run_write_transaction(lambda s: users.record_sign_in(s.get(User, user_id)), concurrent=True)
        login_throttle.record_success(username)
        set_session_cookie(response, user_id=user_id, session_version=session_version)
        return

    # The environment password: the only sign-in without accounts, and the way
    # back in while user accounts are on but no administrator can sign in.
    if not verify_admin_password_hash(data.passwordHash):
        login_throttle.record_failure(username, address)
        raise _login_error("password", "Incorrect password")
    login_throttle.record_success(username)
    set_session_cookie(response, recovery=accounts)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def password_login(data: LoginInput, request: Request, response: Response) -> None:
    address = request.client.host if request.client else None
    await run_in_threadpool(_sign_in, data, response, address)
    # Do not return a new Response object; returning here allows FastAPI to
    # use the provided 'response' with the Set-Cookie header attached.
    return


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    clear_session_cookie(response)
    # Do not return a new Response object; returning here allows FastAPI to
    # use the provided 'response' with the Set-Cookie header attached.
    return


@router.get("/me", dependencies=[signed_in()], response_model=AuthMeRead)
def auth_me(request: Request) -> AuthMeRead:
    """Who is signed in, and what they may see and change."""
    access = request_access(request)
    with db_session() as s:
        return describe_access(s, access)


@router.post("/password", dependencies=[signed_in()], status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeInput, request: Request, response: Response) -> None:
    """Choose a new password for the signed-in account. Other sessions are signed out."""
    access = request_access(request)
    if access.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The environment password is changed in VODLoft's environment, not here.",
        )
    def work(s):
        user = s.get(User, access.user_id)
        users.change_own_password(user, body.current_password_hash, body.new_password_hash)
        return user.session_version

    session_version = run_write_transaction(work)
    set_session_cookie(response, user_id=access.user_id, session_version=session_version)
    return
