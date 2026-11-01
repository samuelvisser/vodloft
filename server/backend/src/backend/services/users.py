"""User accounts: who they are, what they may do, and keeping one administrator.

Passwords never reach the server in plain text. The browser derives a value
from the password (see ``derive_admin_password_client_value``) and VODLoft
stores an scrypt hash of that value, exactly as it does for the environment
password.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Settings, User, UserAccess, UserSourceAccess
from backend.security.access import (
    ADMINISTRATOR_TEMPLATE,
    AREA_LEVELS,
    TEMPLATES,
    Access,
    Area,
    Level,
    SourceLimit,
    is_administrator_levels,
)
from config.security.passwords import hash_password_scrypt, verify_scrypt


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")

# Verified when a username does not exist, so a wrong username takes as long as a wrong password.
_UNKNOWN_USER_HASH = hash_password_scrypt("vodloft-unknown-user")


class UserError(ValueError):
    """A request about users that VODLoft refuses, with the field it is about."""

    def __init__(self, message: str, *, field: Optional[str] = None, status_code: int = 422):
        super().__init__(message)
        self.field = field
        self.status_code = status_code


class LastAdministratorError(UserError):
    def __init__(self) -> None:
        super().__init__(
            "VODLoft needs at least one enabled administrator. Make another user an administrator first.",
            status_code=409,
        )


@dataclass(frozen=True)
class AccessList:
    """Everything an administrator sets for a user besides their name and password."""

    levels: Mapping[Area, Level]
    template_key: Optional[str] = None
    # ``None``: every Source. Otherwise Source id -> domains (``None``: all its domains).
    sources: Optional[Mapping[str, Optional[tuple[str, ...]]]] = None
    members_only: bool = False
    delete_files: bool = False

    @classmethod
    def from_template(cls, key: str) -> "AccessList":
        template = TEMPLATES[key]
        return cls(levels=template.levels, template_key=key, delete_files=template.delete_files)


# Settings -------------------------------------------------------------------


def _settings_row(session: Session) -> Settings:
    row = session.scalars(select(Settings).order_by(Settings.id).limit(1)).first()
    if row is None:
        row = Settings()
        session.add(row)
        session.flush()
    return row


def accounts_enabled(session: Session) -> bool:
    enabled = session.scalars(select(Settings.user_accounts_enabled).order_by(Settings.id).limit(1)).first()
    return bool(enabled)


# Reading --------------------------------------------------------------------


def levels_of(user: User) -> dict[Area, Level]:
    stored = {row.area: row.level for row in user.access}
    return {area: Level(stored.get(area.value, Level.NONE.value)) for area in Area}


def source_limits_of(user: User) -> Optional[dict[str, SourceLimit]]:
    if user.all_sources:
        return None
    return {
        row.source_key: SourceLimit(
            source_key=row.source_key,
            domains=None if row.domains is None else tuple(row.domains),
        )
        for row in user.source_access
    }


def access_of(user: User) -> Access:
    return Access.for_user(
        user_id=user.id,
        username=user.username,
        levels=levels_of(user),
        source_limits=source_limits_of(user),
        members_only=user.members_only,
        delete_files=user.delete_files,
        must_change_password=user.must_change_password,
        template_key=user.template_key,
        session_version=user.session_version,
    )


def is_administrator(user: User) -> bool:
    return is_administrator_levels(levels_of(user))


def find_user(session: Session, username: str) -> Optional[User]:
    return session.scalars(select(User).where(User.username == username.strip())).first()


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(func.lower(User.username))))


def enabled_administrators(session: Session) -> list[User]:
    users = session.scalars(
        select(User).join(UserAccess).where(
            User.is_enabled.is_(True),
            UserAccess.area == Area.USERS.value,
            UserAccess.level == Level.MANAGE.value,
        )
    )
    return list(users)


def load_session_access(session: Session, user_id: int, session_version: int) -> Optional[Access]:
    """The access behind a signed-in session, or ``None`` when it no longer counts."""
    user = session.get(User, user_id)
    if user is None or not user.is_enabled or user.session_version != session_version:
        return None
    return access_of(user)


# Signing in -----------------------------------------------------------------


def authenticate(session: Session, username: str, password_hash: str) -> Optional[User]:
    user = find_user(session, username) if username.strip() else None
    if user is None:
        verify_scrypt(password_hash, _UNKNOWN_USER_HASH)
        return None
    if not verify_scrypt(password_hash, user.password_hash):
        return None
    if not user.is_enabled:
        return None
    return user


def record_sign_in(user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)


def change_own_password(user: User, current_password_hash: str, new_password_hash: str) -> None:
    if not verify_scrypt(current_password_hash, user.password_hash):
        raise UserError("That is not your current password.", field="currentPassword", status_code=400)
    if verify_scrypt(new_password_hash, user.password_hash):
        raise UserError("Choose a password that differs from the current one.", field="newPassword")
    user.password_hash = hash_password_scrypt(new_password_hash)
    user.must_change_password = False
    user.session_version += 1


# Changing -------------------------------------------------------------------


def _validate_username(session: Session, username: str, *, current: Optional[User] = None) -> str:
    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise UserError(
            "Use 2 to 64 letters, digits, dots, dashes or underscores, starting with a letter or digit.",
            field="username",
        )
    existing = find_user(session, username)
    if existing is not None and existing is not current:
        raise UserError("Another user already has this username.", field="username", status_code=409)
    return username


def _validate_levels(levels: Mapping[Area, Level]) -> dict[Area, Level]:
    resolved: dict[Area, Level] = {}
    for area in Area:
        level = Level(levels.get(area, Level.NONE))
        if level not in AREA_LEVELS[area]:
            raise UserError(f"{area.value} cannot be set to {level.value}.", field="levels")
        resolved[area] = level
    return resolved


def _apply_access(user: User, access: AccessList) -> None:
    levels = _validate_levels(access.levels)
    administrator = is_administrator_levels(levels)
    if access.template_key is not None and access.template_key not in TEMPLATES:
        raise UserError("Unknown template.", field="templateKey")
    if administrator and access.sources is not None:
        raise UserError("Administrators may always use every Source.", field="sources")
    if administrator:
        # An administrator can give themselves everything, so they are given it.
        levels = dict(TEMPLATES[ADMINISTRATOR_TEMPLATE].levels)

    by_area = {row.area: row for row in user.access}
    for area, level in levels.items():
        row = by_area.get(area.value)
        if row is None:
            user.access.append(UserAccess(area=area.value, level=level.value))
        else:
            row.level = level.value
    user.template_key = access.template_key

    if access.sources is None:
        user.all_sources = True
        user.source_access.clear()
    else:
        user.all_sources = False
        wanted = {key: domains for key, domains in access.sources.items()}
        user.source_access[:] = [row for row in user.source_access if row.source_key in wanted]
        by_source = {row.source_key: row for row in user.source_access}
        for key, domains in wanted.items():
            stored = None if domains is None else sorted({d.strip().lower().lstrip(".") for d in domains if d.strip()})
            if stored == []:
                raise UserError("List at least one domain, or allow all of the Source's domains.", field="sources")
            row = by_source.get(key)
            if row is None:
                user.source_access.append(UserSourceAccess(source_key=key, domains=stored))
            else:
                row.domains = stored
    user.members_only = administrator or access.members_only
    user.delete_files = administrator or access.delete_files


def create_user(
    session: Session,
    *,
    username: str,
    password_hash: str,
    access: AccessList,
    created_by: Optional[User] = None,
    must_change_password: bool = True,
) -> User:
    user = User(
        username=_validate_username(session, username),
        password_hash=hash_password_scrypt(password_hash),
        is_enabled=True,
        must_change_password=must_change_password,
        session_version=1,
        created_by=created_by,
        access=[],
        source_access=[],
    )
    _apply_access(user, access)
    session.add(user)
    session.flush()
    return user


def _would_leave_no_administrator(session: Session, user: User) -> bool:
    if not accounts_enabled(session):
        return False
    return not any(admin.id != user.id for admin in enabled_administrators(session))


def update_user(
    session: Session,
    user: User,
    *,
    username: Optional[str] = None,
    access: Optional[AccessList] = None,
    enabled: Optional[bool] = None,
) -> None:
    was_administrator = user.is_enabled and is_administrator(user)
    if username is not None:
        user.username = _validate_username(session, username, current=user)
    if access is not None:
        demoted = was_administrator and not is_administrator_levels(_validate_levels(access.levels))
        if demoted and _would_leave_no_administrator(session, user):
            raise LastAdministratorError()
        _apply_access(user, access)
        # A changed access list takes effect on the next request, so nobody needs signing out.
    if enabled is not None and enabled != user.is_enabled:
        if not enabled and was_administrator and _would_leave_no_administrator(session, user):
            raise LastAdministratorError()
        user.is_enabled = enabled
        if not enabled:
            user.session_version += 1
    session.flush()


def reset_password(user: User, password_hash: str, *, must_change: bool = True) -> None:
    user.password_hash = hash_password_scrypt(password_hash)
    user.must_change_password = must_change
    user.session_version += 1


def sign_out_everywhere(user: User) -> None:
    user.session_version += 1


def delete_user(session: Session, user: User) -> None:
    if user.is_enabled and is_administrator(user) and _would_leave_no_administrator(session, user):
        raise LastAdministratorError()
    session.delete(user)
    session.flush()


def set_accounts_enabled(
    session: Session,
    enabled: bool,
    *,
    first_administrator: Optional[tuple[str, str]] = None,
) -> Optional[User]:
    """Turn user accounts on or off.

    Turning them on needs an enabled administrator. When none exists yet,
    ``first_administrator`` (username, password hash) creates one, and it is
    returned so the caller can sign it in.
    """
    row = _settings_row(session)
    created: Optional[User] = None
    if enabled and not row.user_accounts_enabled:
        if not enabled_administrators(session):
            if first_administrator is None:
                raise UserError(
                    "Create the first administrator to turn user accounts on.", field="firstAdministrator",
                )
            username, password_hash = first_administrator
            created = create_user(
                session,
                username=username,
                password_hash=password_hash,
                access=AccessList.from_template(ADMINISTRATOR_TEMPLATE),
                must_change_password=False,
            )
    row.user_accounts_enabled = enabled
    session.flush()
    return created
