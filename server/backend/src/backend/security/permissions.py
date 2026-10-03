"""Local permissions are independent from upstream and media-server accounts."""

import re
from dataclasses import dataclass, field

from fastapi import HTTPException, Request
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.vodloft import LocalUser
from backend.security.auth import Session, SESSION_COOKIE_NAME
from config.security.passwords import verify_scrypt


@dataclass(frozen=True)
class Principal:
    key: str = "admin"
    username: str = "admin"
    role: str = "admin"
    can_subscribe: bool = True
    auto_approve: bool = True
    request_quota: int = 100000
    connection_ids: list[int] = field(default_factory=list)
    target_ids: list[int] = field(default_factory=list)

    @property
    def manages_library(self) -> bool:
        return self.role in {"admin", "manager"}

    def can_use_connection(self, connection_id: int | None) -> bool:
        return connection_id is None or self.role == "admin" or connection_id in self.connection_ids

    def can_use_target(self, target_id: int) -> bool:
        return self.role == "admin" or target_id in self.target_ids


def user_enabled(key: str) -> bool:
    with get_session() as session:
        user = session.get(LocalUser, key)
        return bool(user and user.enabled)


def verify_user_password(username: str, candidate: str) -> str | None:
    with get_session() as session:
        user = session.scalar(select(LocalUser).where(LocalUser.username == username.strip().casefold()))
        return user.key if user and user.enabled and verify_scrypt(candidate, user.password_hash) else None


def principal(request: Request) -> Principal:
    if hasattr(request.state, "principal"):
        return request.state.principal
    token = Session.from_token(request.cookies.get(SESSION_COOKIE_NAME))
    if not token or token.user_key == "admin":
        return Principal()
    with get_session() as session:
        user = session.get(LocalUser, token.user_key)
        if not user or not user.enabled:
            raise HTTPException(401, "Local account is disabled")
        return Principal(user.key, user.username, user.role, user.can_subscribe,
            user.auto_approve, user.request_quota, user.connection_ids, user.target_ids)


def require_connection(request: Request, connection_id: int | None) -> None:
    if not principal(request).can_use_connection(connection_id):
        raise HTTPException(403, "This local account does not have access to that Source connection")


def allowed_api(actor: Principal, method: str, path: str) -> bool:
    if actor.role == "admin":
        return True
    if method == "GET" and path in {"/api/onboarding/status", "/api/meta"}:
        return True
    prefix = "/api/vodloft"
    if not path.startswith(prefix + "/"):
        return False
    path = path[len(prefix):]
    if method in {"GET", "HEAD"} and re.fullmatch(r"/stream/[A-Za-z0-9_-]+(?:/segment/[a-f0-9]+)?", path):
        return True  # Playback handlers enforce ownership and current Source grants.
    if (method == "GET" and (path == "/integrations/rss" or re.fullmatch(r"/integrations/\d+/users", path)) or
        method == "PUT" and re.fullmatch(r"/integrations/\d+/users", path) or
        method == "DELETE" and re.fullmatch(r"/integrations/\d+/users/[A-Za-z0-9_-]+", path) or
        method == "POST" and re.fullmatch(r"/integrations/(?:exports|rss-items)/\d+/progress/pull", path)):
        return True  # Handlers verify the granted server and the user's explicit identity.
    if method == "GET":
        return (path in {"/me", "/home", "/library", "/profiles", "/domains", "/sources",
            "/sources/domains", "/sources/connections", "/requests", "/integrations"} or
            bool(re.fullmatch(r"/(?:library/\d+(?:/(?:progress|artwork|integrations|stream-profiles|download-profiles|history))?|jobs/\d+|sources/[^/]+/(?:manifest|domains|search)|stream-profiles/\d+/admissions)", path)))
    if method == "POST" and (path in {"/resolve", "/import"} or re.fullmatch(
            r"/(?:library/\d+/(?:watch|requests)|sources/[^/]+/(?:match|entries))", path)):
        return True
    if method == "POST" and re.fullmatch(r"/profiles/\d+/preview", path):
        return True
    if method == "PUT" and re.fullmatch(r"/library/\d+/progress", path):
        return True
    if method in {"POST", "DELETE"} and re.fullmatch(
            r"/(?:stream-profiles/\d+|library/\d+)/feed(?:/rotate)?", path):
        return actor.can_subscribe
    if method == "DELETE" and re.fullmatch(r"/requests/\d+", path):
        return True
    if actor.manages_library:
        return (method == "POST" and bool(re.fullmatch(r"/requests/\d+/(?:approve|reject)", path)) or
                method == "PUT" and bool(re.fullmatch(r"/library/\d+/metadata", path)) or
                method == "DELETE" and bool(re.fullmatch(r"/library/\d+", path)))
    return False
