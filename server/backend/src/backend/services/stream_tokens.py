"""The secret tokens in the addresses apps open without signing in: a stream profile's own, a user's, or the
install's, which open one profile or all of a user's profiles of a type at once."""
from __future__ import annotations

from typing import Optional, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.db.models import Settings
from backend.db.models.stream_profile import StreamProfileBase
from backend.db.models.user import User
from backend.services import users
from backend.services.errors import NotFoundError
from backend.services.stream_episodes import owner_may_stream

Profile = TypeVar("Profile", bound=StreamProfileBase)


def profiles_for_token(s: Session, token: str, model: type[Profile], *order_by, what: str) -> list[Profile]:
    """The enabled profiles of this type that an address with this token opens, in ``order_by`` order.

    The token is a profile's own, a user's stream token (their own profiles) or, in an install without
    user accounts, the install's stream token (every profile). ``what`` names the address in its
    NotFoundError.
    """
    query = (
        s.query(model)
        .options(joinedload(model.collection))
        .filter(model.enable_profile.is_(True))
        .order_by(*order_by, model.id)
    )
    own = query.filter(model.token == token).one_or_none()
    if own is not None:
        if not owner_may_stream(s, own):
            raise NotFoundError(what)
        return [own]

    user = s.scalars(select(User).where(User.stream_token == token)).one_or_none()
    if user is not None:
        if not user.is_enabled:
            raise NotFoundError(what)
        return query.filter(model.owner_user_id == user.id).all()

    install = s.scalars(select(Settings).where(Settings.stream_token == token)).first()
    if install is not None and not install.user_accounts_enabled:
        return [profile for profile in query.all() if owner_may_stream(s, profile)]
    raise NotFoundError(what)


def stream_token_holder(s: Session, user_id: Optional[int]) -> User | Settings:
    """Where the stream token of whoever is signed in is kept: their account, or the install without accounts."""
    if user_id is not None:
        user = s.get(User, user_id)
        if user is None:
            raise NotFoundError("User")
        return user
    return users.settings_row(s)
