from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from backend.api.models.auth import SourceLimitRead
from backend.api.models.user import (
    AccessAreaRead,
    AccessOptionsRead,
    AccessTemplateRead,
    UserAccessInput,
    UserAccountsSettingsRead,
    UserAccountsSettingsUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)
from backend.db.models import User
from backend.security.access import AREA_LEVELS, TEMPLATES, Access, Area, Level
from backend.security.auth import clear_session_cookie, set_session_cookie
from backend.services import users
from backend.services.users import AccessList, UserError
from config import get_settings


def _access_list(body: UserAccessInput) -> AccessList:
    try:
        levels = {Area(area): Level(level) for area, level in body.levels.items()}
    except ValueError as exc:
        raise UserError(str(exc), field="levels") from exc
    return AccessList(
        levels=levels,
        template_key=body.template_key,
        sources=None if body.sources is None else {
            limit.source_key: None if limit.domains is None else tuple(limit.domains)
            for limit in body.sources
        },
        members_only=body.members_only,
        delete_files=body.delete_files,
    )


def user_read(user: User) -> UserRead:
    access = users.access_of(user)
    limits = users.source_limits_of(user)
    return UserRead(
        id=user.id,
        username=user.username,
        enabled=user.is_enabled,
        must_change_password=user.must_change_password,
        template_key=user.template_key,
        administrator=access.is_administrator,
        levels={area.value: level.value for area, level in users.levels_of(user).items()},
        sources=None if limits is None else [
            SourceLimitRead(source_key=limit.source_key, domains=None if limit.domains is None else list(limit.domains))
            for limit in limits.values()
        ],
        members_only=user.members_only,
        delete_files=user.delete_files,
        created_by=user.created_by.username if user.created_by else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def list_users(session: Session) -> list[UserRead]:
    return [user_read(user) for user in users.list_users(session)]


def get_user(session: Session, user_id: int) -> UserRead:
    return user_read(_user(session, user_id))


def create_user(session: Session, body: UserCreate, acting: Access) -> UserRead:
    creator = session.get(User, acting.user_id) if acting.user_id is not None else None
    user = users.create_user(
        session,
        username=body.username,
        password_hash=body.password_hash,
        access=_access_list(body.access),
        created_by=creator,
    )
    session.commit()
    session.refresh(user)
    return user_read(user)


def update_user(session: Session, user_id: int, body: UserUpdate) -> UserRead:
    user = _user(session, user_id)
    users.update_user(
        session,
        user,
        username=body.username,
        enabled=body.enabled,
        access=None if body.access is None else _access_list(body.access),
    )
    session.commit()
    session.refresh(user)
    return user_read(user)


def reset_password(session: Session, user_id: int, password_hash: str) -> None:
    users.reset_password(_user(session, user_id), password_hash)
    session.commit()


def sign_out_everywhere(session: Session, user_id: int, acting: Access, response: Response) -> None:
    user = _user(session, user_id)
    users.sign_out_everywhere(user)
    session.commit()
    if user.id == acting.user_id:
        clear_session_cookie(response)


def delete_user(session: Session, user_id: int, stream_profiles: str, acting: Access) -> None:
    users.delete_user(session, _user(session, user_id), stream_profiles=stream_profiles, heir_id=acting.user_id)
    session.commit()


def accounts_settings(session: Session) -> UserAccountsSettingsRead:
    return UserAccountsSettingsRead(
        enabled=users.accounts_enabled(session),
        environment_password=get_settings().admin_auth.enabled,
        administrators=len(users.enabled_administrators(session)),
    )


def update_accounts_settings(
    session: Session, body: UserAccountsSettingsUpdate, acting: Access, response: Response,
) -> UserAccountsSettingsRead:
    first: Optional[tuple[str, str]] = None
    if body.first_administrator is not None:
        first = (body.first_administrator.username, body.first_administrator.password_hash)
    was_enabled = users.accounts_enabled(session)
    created = users.set_accounts_enabled(session, body.enabled, first_administrator=first)
    session.commit()

    if body.enabled and not was_enabled and not acting.is_user:
        # A shared-password session ends with accounts on. Keep the person signed
        # in as the administrator they just created; otherwise they sign in as one.
        if created is not None:
            set_session_cookie(response, user_id=created.id, session_version=created.session_version)
        else:
            clear_session_cookie(response)
    elif not body.enabled and was_enabled:
        # Without accounts only the shared password signs in; this session was a user's.
        clear_session_cookie(response)
    return accounts_settings(session)


def access_options() -> AccessOptionsRead:
    return AccessOptionsRead(
        areas=[AccessAreaRead(area=area.value, levels=[level.value for level in AREA_LEVELS[area]]) for area in Area],
        templates=[
            AccessTemplateRead(
                key=template.key,
                name=template.name,
                levels={area.value: level.value for area, level in template.levels.items()},
                delete_files=template.delete_files,
            )
            for template in TEMPLATES.values()
        ],
    )


__all__ = [
    "UserError",
    "access_options",
    "accounts_settings",
    "create_user",
    "delete_user",
    "get_user",
    "list_users",
    "reset_password",
    "sign_out_everywhere",
    "update_accounts_settings",
    "update_user",
]
