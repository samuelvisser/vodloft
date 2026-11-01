from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.responses import Response

from config import get_settings
from config.security.admin_auth import AdminAuth
from .access import Access
from .crypto import encrypt_text, decrypt_text

SESSION_COOKIE_NAME = "vodloft_session"


@dataclass
class Session:
    exp: int
    iat: int
    # Set when a user signed in with their own account.
    uid: Optional[int] = None
    ver: Optional[int] = None
    # Signed in with the environment password while user accounts are on.
    rec: bool = False

    def to_token(self) -> bytes:
        payload: dict[str, object] = {"exp": self.exp, "iat": self.iat}
        if self.uid is not None:
            payload.update(uid=self.uid, ver=self.ver)
        if self.rec:
            payload["rec"] = True
        return encrypt_text(json.dumps(payload)) or b""

    @staticmethod
    def from_token(token: str | bytes | None) -> Optional["Session"]:
        raw = decrypt_text(token)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            uid = payload.get("uid")
            return Session(
                exp=int(payload["exp"]),
                iat=int(payload["iat"]),
                uid=None if uid is None else int(uid),
                ver=None if uid is None else int(payload["ver"]),
                rec=bool(payload.get("rec", False)),
            )
        except Exception:
            return None


def _now() -> int:
    return int(time.time())


def set_session_cookie(
    resp: Response,
    ttl_seconds: Optional[int] = None,
    *,
    user_id: Optional[int] = None,
    session_version: Optional[int] = None,
    recovery: bool = False,
) -> None:
    ttl_seconds = ttl_seconds or get_settings().login_session.ttl_seconds
    now = _now()
    sess = Session(exp=now + ttl_seconds, iat=now, uid=user_id, ver=session_version, rec=recovery)
    token = sess.to_token().decode("utf-8")
    # Cookies: secure False by default (local dev). If BEHIND_HTTPS is set, mark secure.
    secure = os.environ.get("BEHIND_HTTPS", "0").lower() in ("1", "true", "yes")
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl_seconds,
        expires=ttl_seconds,
        secure=secure,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")


def current_session(request: Request) -> Optional[Session]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    sess = Session.from_token(token)
    if not sess or sess.exp <= _now():
        return None
    return sess


def resolve_access(request: Request) -> Optional[Access]:
    """Who is behind this request, or ``None`` when nobody is signed in.

    This reads the database, so call it from a worker thread in async code.
    """
    from backend.db import get_session
    from backend.services import users

    with get_session() as db:
        if not users.accounts_enabled(db):
            # Without accounts, only sessions from the shared password count:
            # a session from a user account must not outlive turning accounts off.
            if not AdminAuth().is_enabled:
                return Access.full()
            sess = current_session(request)
            if sess is None or sess.uid is not None or sess.rec:
                return None
            return Access.full()

        sess = current_session(request)
        if sess is None:
            return None
        if sess.uid is not None and sess.ver is not None:
            return users.load_session_access(db, sess.uid, sess.ver)
        if sess.rec and AdminAuth().is_enabled and not users.enabled_administrators(db):
            # The environment password is the way back in while no administrator can sign in.
            return Access.full(recovery=True)
        return None


def request_access(request: Request) -> Access:
    """The access the auth guard resolved for this request."""
    access = getattr(request.state, "access", None)
    if access is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return access


def verify_admin_password_hash(password_hash: str) -> bool:
    return AdminAuth().verify(password_hash)
