from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Final

from sqlalchemy.orm import Session

from backend.db.models import ApplicationSettings

SESSION_COOKIE: Final = "vodloft_session"
SESSION_LIFETIME_SECONDS: Final = 30 * 24 * 60 * 60


def ensure_application_settings(session: Session) -> ApplicationSettings:
    settings = session.get(ApplicationSettings, 1)
    if settings is None:
        settings = ApplicationSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
        )
        return hmac.compare_digest(digest, _unb64(expected))
    except (ValueError, TypeError):
        return False


def create_session_token(username: str, secret: str, lifetime: int = SESSION_LIFETIME_SECONDS) -> str:
    expires = int(time.time()) + lifetime
    payload = f"{username}\n{expires}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify_session_token(token: str | None, username: str, secret: str) -> bool:
    if not token:
        return False
    try:
        payload_text, signature_text = token.split(".", 1)
        payload = _unb64(payload_text)
        signature = _unb64(signature_text)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        token_username, expires_text = payload.decode("utf-8").split("\n", 1)
        return token_username == username and int(expires_text) >= int(time.time())
    except (ValueError, UnicodeDecodeError):
        return False


def authenticated(token: str | None, settings: ApplicationSettings) -> bool:
    if not settings.auth_enabled or not settings.admin_password_hash:
        return True
    return verify_session_token(token, settings.admin_username, settings.session_secret)


def valid_rss_token(token: str | None, settings: ApplicationSettings) -> bool:
    return bool(token) and secrets.compare_digest(token, settings.rss_token)
