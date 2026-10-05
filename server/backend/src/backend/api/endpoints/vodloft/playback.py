"""Session-bound local playback and private Source stream delivery."""

import base64
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import delete, select

from backend.db import get_session
from backend.db.models.vodloft import (Artifact, MediaItem, PlaybackSegment,
    PlaybackSession, SourceReference, SourceConnection)
from backend.source_manager.gateway import SourceGateway, SourceInvocationError, validate_public_url
from backend.source_manager.runtime import runtime_root
from backend.source_manager.connections import source_options
from backend.source_manager.capabilities import reference_capabilities
from backend.security.permissions import principal
from config import get_settings

router = APIRouter(prefix="/vodloft", tags=["VodLoft playback"])
_URI = re.compile(r'URI="([^"]+)"')
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 4 * 1024 * 1024


def _key() -> bytes:
    root = runtime_root().parent
    root.mkdir(parents=True, exist_ok=True)
    path = root / "playback.key"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as output:
            output.write(Fernet.generate_key())
    return path.read_bytes()


def _seal(value: dict | str) -> str:
    return Fernet(_key()).encrypt(json.dumps(value).encode()).decode()


def _unseal(value: str):
    return json.loads(Fernet(_key()).decrypt(value.encode()))


def _session(token: str, request: Request):
    if len(token) > 128:
        raise HTTPException(404, "Playback session not found")
    with get_session() as db:
        session = db.scalar(select(PlaybackSession).where(
            PlaybackSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if not session or session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(404, "Playback session expired")
        actor = principal(request)
        if session.user_key != actor.key:
            raise HTTPException(404, "Playback session not found")
        if session.reference_id:
            reference = db.get(SourceReference, session.reference_id)
            if not reference or not actor.can_use_connection(reference.connection_id):
                raise HTTPException(403, "Playback Source access was withdrawn")
            connection = db.get(SourceConnection, reference.connection_id) if reference.connection_id else None
            if connection and not connection.enabled:
                raise HTTPException(403, "Playback Source connection is disabled")
        return session.id, session.source_id, session.transport, _unseal(session.lease_ciphertext)


@router.post("/library/{item_id}/watch")
def watch(item_id: int, request: Request, reference_id: int | None = None):
    """Prefer the latest local file; otherwise acquire a private upstream lease."""
    with get_session() as db:
        item = db.get(MediaItem, item_id)
        if not item or item.kind == "collection":
            raise HTTPException(404, "Playable media item not found")
        local = next((artifact for artifact in db.scalars(select(Artifact).where(
            Artifact.item_id == item_id).order_by(Artifact.id.desc())).all()
            if Path(artifact.path).is_file()), None)
        if local:
            path = Path(local.path).resolve()
            root = Path(get_settings().download_settings.download_root).resolve() / "vodloft"
            if not path.is_relative_to(root):
                raise HTTPException(404, "Local file is unavailable")
            token = secrets.token_urlsafe(36)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
            db.add(PlaybackSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                user_key=principal(request).key,
                item_id=item_id, source_id="local", reference_id=None,
                transport="file", lease_ciphertext=_seal({"path": str(path)}),
                expires_at=expires_at))
            db.commit()
            return {"transport": "file", "url": str(request.url_for(
                "vodloft_stream", token=token)), "expires_at": expires_at.isoformat()}
        references = db.scalars(select(SourceReference).where(SourceReference.item_id == item_id)).all()
        eligible = [ref for ref in references if (reference_id is None or ref.id == reference_id)
                    and principal(request).can_use_connection(ref.connection_id)]
        if len(eligible) != 1:
            raise HTTPException(409, "Select one Source account for upstream playback")
        reference = eligible[0]
        policy = reference_capabilities(db, reference)
        if "stream_lease" not in policy.effective_capabilities:
            raise HTTPException(409, policy.capability_reasons["stream_lease"])
        options = source_options(db, reference.source_id, reference.connection_id)
        source_id, url, selected_id = reference.source_id, reference.url, reference.id
    try:
        gateway = SourceGateway()
        lease = gateway.stream_lease(source_id, url, **options)
    except Exception as exc:
        raise HTTPException(502, "Upstream playback is unavailable") from exc
    token = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    lease_data = lease.model_dump()
    lease_data["_command"] = gateway.commands.get(source_id)
    with get_session() as db:
        db.add(PlaybackSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_key=principal(request).key,
            item_id=item_id, source_id=source_id, reference_id=selected_id,
            transport=lease.transport, lease_ciphertext=_seal(lease_data),
            expires_at=expires_at))
        db.commit()
    return {"transport": lease.transport, "url": str(request.url_for(
        "vodloft_stream", token=token)), "expires_at": expires_at.isoformat()}


def _identity(url: str) -> dict:
    parsed = urlsplit(url)
    return {"host": parsed.netloc, "path": parsed.path}


def _child(db, session_id: int, parent_url: str, relative: str, token: str, request: Request,
           ancestors: list[dict], lease_url: str) -> str:
    candidate = urljoin(parent_url, relative)
    validate_public_url(candidate)
    lineage = [*ancestors, _identity(candidate)]
    segment_id = hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest()[:36]
    descriptor = {"url": candidate, "ancestors": lineage, "lease_url": lease_url}
    segment = db.scalar(select(PlaybackSegment).where(PlaybackSegment.session_id == session_id,
                                                     PlaybackSegment.public_id == segment_id))
    if segment:
        segment.url_ciphertext = _seal(descriptor)
    else:
        db.add(PlaybackSegment(session_id=session_id, public_id=segment_id,
                              url_ciphertext=_seal(descriptor)))
        db.flush()
    return str(request.url_for("vodloft_stream_child", token=token, segment_id=segment_id))


def _playlist(body: bytes, parent_url: str, session_id: int, token: str, request: Request,
              ancestors: list[dict], lease_url: str) -> bytes:
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(502, "Upstream playlist exceeds the supported size")
    text = body.decode("utf-8-sig")
    if "#EXTM3U" not in text[:256]:
        raise HTTPException(502, "Upstream playlist is invalid")
    with get_session() as db:
        output = []
        children = 0
        for line in text.splitlines():
            if children > 10000:
                raise HTTPException(502, "Upstream playlist has too many media references")
            if line.startswith("#"):
                children += len(_URI.findall(line))
                line = _URI.sub(lambda match: 'URI="' + _child(db, session_id,
                    parent_url, match.group(1), token, request, ancestors, lease_url) + '"', line)
            elif line.strip():
                children += 1
                line = _child(db, session_id, parent_url, line.strip(), token, request, ancestors, lease_url)
            output.append(line)
        db.commit()
    return ("\n".join(output) + "\n").encode()


def _gateway(source_id: str, lease: dict) -> SourceGateway:
    return SourceGateway({source_id: lease["_command"]}) if lease.get("_command") else SourceGateway()


def _renew(session_id: int, source_id: str, transport: str, lease: dict, *, force: bool = False) -> dict:
    expiry = lease.get("expires_at")
    try:
        expired = expiry is not None and datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= (
            datetime.now(timezone.utc) + timedelta(seconds=15))
    except (ValueError, TypeError):
        expired = True
    if not force and not expired:
        return lease
    if not lease.get("renewable"):
        raise HTTPException(409, "The playback lease expired; start a new session")
    with get_session() as db:
        session = db.get(PlaybackSession, session_id)
        reference = db.get(SourceReference, session.reference_id)
        if not reference:
            raise HTTPException(409, "The playback Source reference is unavailable")
        try:
            options = source_options(db, source_id, reference.connection_id)
            renewed = _gateway(source_id, lease).stream_lease(source_id, reference.url, **options)
        except Exception as exc:
            raise HTTPException(502, "The Source could not renew this playback session") from exc
        same_representation = (renewed.representation_id == lease["representation_id"]
            if lease.get("representation_id") else _identity(renewed.url) == _identity(lease["url"]))
        if renewed.transport != transport or not same_representation:
            raise HTTPException(409, "The active playback representation changed; start a new session")
        lease = {**lease, **renewed.model_dump()}
        session.lease_ciphertext = _seal(lease)
        db.commit()
    return lease


def _fetch(source_id: str, lease: dict, url: str, byte_range: str | None = None) -> tuple[dict, bytes]:
    validate_public_url(url)
    fetched = _gateway(source_id, lease).call(source_id, "stream_fetch", timeout=40,
        url=url, headers=lease.get("headers", {}), byte_range=byte_range)
    return fetched, base64.b64decode(fetched["data"], validate=True)


def _refresh_child(source_id: str, lease: dict, descriptor: dict) -> dict:
    """Re-resolve signed URIs through the same manifest lineage, preserving paths."""
    current = lease["url"]
    if len(descriptor["ancestors"]) > 6:
        raise HTTPException(502, "Upstream playlist nesting exceeds the supported depth")
    for identity in descriptor["ancestors"]:
        fetched, body = _fetch(source_id, lease, current)
        if len(body) > 2 * 1024 * 1024 or not body.startswith(b"#EXTM3U"):
            raise HTTPException(409, "The active playlist representation is unavailable")
        urls = []
        for line in body.decode("utf-8-sig").splitlines():
            values = _URI.findall(line) if line.startswith("#") else [line.strip()] if line.strip() else []
            urls.extend(urljoin(fetched["url"], value) for value in values)
        matches = list(dict.fromkeys(url for url in urls if _identity(url) == identity))
        if len(matches) != 1:
            raise HTTPException(409, "This HLS segment is no longer in the active representation")
        current = matches[0]
    return {**descriptor, "url": current, "lease_url": lease["url"]}


def _serve(token: str, request: Request, segment_id: str | None = None):
    session_id, source_id, transport, lease = _session(token, request)
    if transport == "file":
        if segment_id:
            raise HTTPException(404, "Playback segment not found")
        path = Path(lease["path"]).resolve()
        root = Path(get_settings().download_settings.download_root).resolve() / "vodloft"
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Local representation is unavailable")
        return FileResponse(path, headers={"Cache-Control": "private, no-store"})
    lease = _renew(session_id, source_id, transport, lease)
    descriptor = None
    if segment_id:
        with get_session() as db:
            segment = db.scalar(select(PlaybackSegment).where(
                PlaybackSegment.session_id == session_id,
                PlaybackSegment.public_id == segment_id))
            if not segment:
                raise HTTPException(404, "Playback segment not found")
            descriptor = _unseal(segment.url_ciphertext)
        if descriptor["lease_url"] != lease["url"]:
            try:
                descriptor = _refresh_child(source_id, lease, descriptor)
            except SourceInvocationError as exc:
                raise HTTPException(502, "Upstream playlist is unavailable") from exc
            with get_session() as db:
                db.scalar(select(PlaybackSegment).where(PlaybackSegment.session_id == session_id,
                    PlaybackSegment.public_id == segment_id)).url_ciphertext = _seal(descriptor)
                db.commit()
        url = descriptor["url"]
    else:
        url = lease["url"]
    requested = request.headers.get("range")
    byte_range = None
    if requested:
        match = _RANGE.fullmatch(requested)
        if not match:
            raise HTTPException(416, "Unsupported byte range")
        first, last = match.groups()
        if not first and not last:
            raise HTTPException(416, "Unsupported byte range")
        if first:
            start = int(first)
            end = min(int(last), start + _CHUNK - 1) if last else start + _CHUNK - 1
            if end < start:
                raise HTTPException(416, "Unsupported byte range")
            byte_range = f"bytes={start}-{end}"
        else:
            length = min(int(last), _CHUNK)
            if length <= 0:
                raise HTTPException(416, "Unsupported byte range")
            byte_range = f"bytes=-{length}"
    elif transport == "http" and segment_id is None:
        byte_range = f"bytes=0-{_CHUNK - 1}"
    try:
        fetched, body = _fetch(source_id, lease, url, byte_range)
    except SourceInvocationError as exc:
        if not lease.get("renewable") or exc.code not in {"authentication_required", "unavailable"}:
            raise HTTPException(502, "Upstream stream is unavailable") from exc
        lease = _renew(session_id, source_id, transport, lease, force=True)
        if descriptor:
            descriptor = _refresh_child(source_id, lease, descriptor)
            url = descriptor["url"]
        else:
            url = lease["url"]
        try:
            fetched, body = _fetch(source_id, lease, url, byte_range)
        except Exception as renewed_exc:
            raise HTTPException(502, "Upstream stream is unavailable") from renewed_exc
    except Exception as exc:
        raise HTTPException(502, "Upstream stream is unavailable") from exc
    media_type = fetched.get("content_type", "application/octet-stream").split(";", 1)[0]
    if body.lstrip(b"\xef\xbb\xbf\r\n\t ").startswith(b"#EXTM3U") or url.split("?", 1)[0].endswith(".m3u8") or media_type in {
        "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/x-mpegurl"}:
        body = _playlist(body, fetched["url"], session_id, token, request,
                         descriptor["ancestors"] if descriptor else [], lease["url"])
        return Response(b"" if request.method == "HEAD" else body, media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
                     "Content-Length": str(len(body))})
    headers = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
        "Accept-Ranges": "bytes"}
    if fetched.get("content_range"):
        headers["Content-Range"] = fetched["content_range"]
    headers["Content-Length"] = str(len(body))
    return Response(b"" if request.method == "HEAD" else body, status_code=206 if fetched.get("status") == 206 else 200,
        media_type=media_type, headers=headers)


@router.api_route("/stream/{token}", methods=["GET", "HEAD"], name="vodloft_stream")
def stream(token: str, request: Request):
    return _serve(token, request)


@router.api_route("/stream/{token}/segment/{segment_id}", methods=["GET", "HEAD"], name="vodloft_stream_child")
def stream_child(token: str, segment_id: str, request: Request):
    return _serve(token, request, segment_id)


def expire_sessions():
    with get_session() as db:
        expired = select(PlaybackSession.id).where(PlaybackSession.expires_at < datetime.now(timezone.utc))
        db.execute(delete(PlaybackSegment).where(PlaybackSegment.session_id.in_(expired)))
        db.execute(delete(PlaybackSession).where(PlaybackSession.id.in_(expired)))
        db.commit()
