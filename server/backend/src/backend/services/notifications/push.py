"""Push to the installed app: the signing key, the devices people opt in, and sending one message.

Ported from WireLoft. Sending goes through Apprise's Web Push plugin; the device's subscription stays encrypted in
VODLoft's database and is only written to a private temporary folder while one message is sent.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import PushSubscription, PushVapidKey
from backend.security.crypto import decrypt_text, encrypt_text

# Only known browser push services: the endpoint comes from the browser, through VODLoft's API, and must not turn
# a self-hosted VODLoft into a proxy for requests to anywhere.
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)


class PushRejected(ValueError):
    """The browser's subscription cannot be used."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_endpoint(endpoint: str) -> None:
    if len(endpoint) > 2048:
        raise PushRejected("The push address is too long")
    try:
        url = urlsplit(endpoint)
        host = (url.hostname or "").lower()
        port = url.port
    except ValueError as exc:
        raise PushRejected("The push address is not valid") from exc
    if (
        url.scheme != "https" or port not in (None, 443) or not host or url.username or url.password or url.fragment
        or not any(host == suffix or host.endswith("." + suffix) for suffix in PUSH_HOST_SUFFIXES)
    ):
        raise PushRejected("This browser's push service is not supported")


def validate_client_keys(p256dh: str, auth: str) -> None:
    try:
        public_bytes = _unb64url(p256dh)
        auth_bytes = _unb64url(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_bytes)
    except (ValueError, TypeError) as exc:
        raise PushRejected("The browser's push keys are not valid") from exc
    if len(public_bytes) != 65 or len(auth_bytes) != 16:
        raise PushRejected("The browser's push keys are not valid")


def _public_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.X962, format=serialization.PublicFormat.UncompressedPoint,
    )


def vapid_key(session: Session) -> ec.EllipticCurvePrivateKey:
    """The installation's signing key, made the first time it is needed."""
    stored = session.get(PushVapidKey, 1)
    if stored is None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        encoded = _b64url(private_key.private_numbers().private_value.to_bytes(32, "big"))
        encrypted = encrypt_text(encoded)
        if encrypted is None:
            raise RuntimeError("VODLoft cannot protect the push signing key")
        session.add(PushVapidKey(id=1, encrypted_private_key=encrypted.decode("ascii")))
        session.flush()
        return private_key
    decoded = decrypt_text(stored.encrypted_private_key)
    if decoded is None:
        raise RuntimeError("VODLoft cannot read its push signing key")
    return ec.derive_private_key(int.from_bytes(_unb64url(decoded), "big"), ec.SECP256R1())


def vapid_public_key(session: Session) -> str:
    return _b64url(_public_bytes(vapid_key(session)))


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def save_subscription(
    session: Session, *, user_id: int | None, endpoint: str, p256dh: str, auth: str, device_name: str,
) -> PushSubscription:
    """Store a device that asked for push messages, or move it to whoever is signed in now."""
    validate_endpoint(endpoint)
    validate_client_keys(p256dh, auth)
    encrypted = encrypt_text(json.dumps({"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}))
    if encrypted is None:
        raise RuntimeError("VODLoft cannot protect the push subscription")
    stored = session.scalar(select(PushSubscription).where(PushSubscription.endpoint_hash == endpoint_hash(endpoint)))
    if stored is None:
        stored = PushSubscription(endpoint_hash=endpoint_hash(endpoint))
        session.add(stored)
    stored.user_id = user_id
    stored.encrypted_subscription = encrypted.decode("ascii")
    stored.device_name = device_name.strip()[:80] or "This device"
    session.flush()
    return stored


def find_subscription(session: Session, endpoint: str) -> PushSubscription | None:
    return session.scalar(select(PushSubscription).where(PushSubscription.endpoint_hash == endpoint_hash(endpoint)))


def send_push(key: ec.EllipticCurvePrivateKey, subscription: PushSubscription, payload: dict) -> str:
    """Send one message to one device: SENT, RETRY, or EXPIRED when the browser revoked it."""
    decrypted = decrypt_text(subscription.encrypted_subscription)
    if decrypted is None:
        return "EXPIRED"
    data = json.loads(decrypted)
    validate_endpoint(data["endpoint"])
    from apprise.plugins.vapid import NotifyVapid

    subscriber = "notifications@vodloft.local"
    with TemporaryDirectory(prefix="vodloft-push-") as directory:
        path = Path(directory)
        keyfile, subfile = path / "vapid.pem", path / "subscriptions.json"
        keyfile.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        subfile.write_text(json.dumps({subscriber: data}), encoding="utf-8")
        keyfile.chmod(0o600)
        subfile.chmod(0o600)
        notifier = NotifyVapid(
            subscriber=subscriber, targets=[subscriber], keyfile=str(keyfile), subfile=str(subfile),
            include_image=False, ttl=3600, request_timeout=8, redirects=False,
        )
        if not notifier.subscriptions.load():
            return "EXPIRED"
        # Push carries VODLoft's own JSON, which the app's service worker shows.
        if notifier.send(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))):
            return "SENT"
        # The plugin drops endpoints the push service answered 404 or 410 for.
        return "EXPIRED" if subscriber not in notifier.subscriptions else "RETRY"
