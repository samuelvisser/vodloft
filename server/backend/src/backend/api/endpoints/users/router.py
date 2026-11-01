from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from backend.api.models.user import (
    AccessOptionsRead,
    UserAccountsSettingsRead,
    UserAccountsSettingsUpdate,
    UserCreate,
    UserPasswordReset,
    UserRead,
    UserUpdate,
)
from backend.app import db_session
from backend.security.access import Access, Area, Level
from backend.security.deps import AccessRequirement, requires

from . import service


router = APIRouter(prefix="/users", tags=["Users"], dependencies=[requires(Area.USERS, Level.MANAGE)])
administrator = AccessRequirement(Area.USERS, Level.MANAGE)


@router.get("/settings", response_model=UserAccountsSettingsRead)
def user_accounts_settings():
    """Whether user accounts are on."""
    with db_session() as s:
        return service.accounts_settings(s)


@router.put("/settings", response_model=UserAccountsSettingsRead)
def user_accounts_settings_update(
    body: UserAccountsSettingsUpdate, response: Response, acting: Access = Depends(administrator),
):
    """Turn user accounts on or off. Turning them on the first time creates the first administrator."""
    with db_session() as s:
        return service.update_accounts_settings(s, body, acting, response)


@router.get("/access-options", response_model=AccessOptionsRead)
def user_access_options():
    """The areas, levels and templates of an access list."""
    return service.access_options()


@router.get("", response_model=list[UserRead])
def user_list():
    with db_session() as s:
        return service.list_users(s)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def user_create(body: UserCreate, acting: Access = Depends(administrator)):
    with db_session() as s:
        return service.create_user(s, body, acting)


@router.get("/{user_id}", response_model=UserRead)
def user_get(user_id: int):
    with db_session() as s:
        return service.get_user(s, user_id)


@router.patch("/{user_id}", response_model=UserRead)
def user_update(user_id: int, body: UserUpdate):
    """Rename, enable, disable or change the access list. A disabled user is signed out everywhere."""
    with db_session() as s:
        return service.update_user(s, user_id, body)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def user_reset_password(user_id: int, body: UserPasswordReset):
    """Set a one-time password the user must change, and sign them out everywhere."""
    with db_session() as s:
        service.reset_password(s, user_id, body.password_hash)
    return Response(status_code=204)


@router.post("/{user_id}/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def user_sign_out_everywhere(user_id: int, response: Response, acting: Access = Depends(administrator)):
    with db_session() as s:
        service.sign_out_everywhere(s, user_id, acting, response)
    response.status_code = 204
    return response


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def user_delete(user_id: int):
    with db_session() as s:
        service.delete_user(s, user_id)
    return Response(status_code=204)
