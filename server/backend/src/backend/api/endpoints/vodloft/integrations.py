"""Delivery targets and verified media-server exports."""

import json
import base64
import logging
import os
import posixpath
import re
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request as UpstreamRequest, build_opener
from xml.etree import ElementTree

from cryptography.fernet import Fernet
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import (Artifact, ArtifactPlacement, CollectionEntry,
    MediaItem, MediaServerExport, MediaServerTarget, PlaybackProgress, SourceReference,
    IntegrationUserMapping, IntegrationFeedDelivery, IntegrationFeedItem, FeedSubscription,
    PublishedEntry, CollectionStreamProfile, LocalUser)
from backend.source_manager.gateway import SourceGateway
from backend.source_manager.runtime import runtime_root
from backend.security.permissions import principal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vodloft", tags=["VodLoft integrations"])


class TargetInput(BaseModel):
    kind: Literal["jellyfin", "plex", "audiobookshelf"]
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    library_id: str = Field(min_length=1, max_length=120)
    local_prefix: str
    server_prefix: str
    api_key: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def server_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Enter an HTTP or HTTPS media-server address without credentials")
        return value.rstrip("/")

    @field_validator("local_prefix", "server_prefix")
    @classmethod
    def absolute_mapping(cls, value):
        if not value.startswith("/") or ".." in Path(value).parts:
            raise ValueError("Path mapping must be an absolute folder")
        return value.rstrip("/") or "/"


class TargetUpdate(TargetInput):
    api_key: str | None = Field(default=None, min_length=1)


class TargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    name: str
    base_url: str
    library_id: str
    local_prefix: str
    server_prefix: str
    enabled: bool


def _key() -> bytes:
    root = runtime_root().parent
    root.mkdir(parents=True, exist_ok=True)
    path = root / "delivery.key"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as output:
            output.write(Fernet.generate_key())
    return path.read_bytes()


def _token(target: MediaServerTarget) -> str:
    return Fernet(_key()).decrypt(target.secret_ciphertext.encode()).decode()


def _serialize(target: MediaServerTarget) -> TargetResponse:
    return TargetResponse.model_validate(target)


@router.get("/integrations")
def targets(request: Request):
    with get_session() as session:
        return [_serialize(t) for t in session.scalars(select(MediaServerTarget)).all()
                if principal(request).can_use_target(t.id)]


@router.post("/integrations", status_code=201)
def add_target(data: TargetInput):
    encrypted = Fernet(_key()).encrypt(data.api_key.encode()).decode()
    with get_session() as session:
        target = MediaServerTarget(**data.model_dump(exclude={"api_key"}), secret_ciphertext=encrypted)
        session.add(target)
        session.commit()
        return _serialize(target)


@router.put("/integrations/{target_id}")
def update_target(target_id: int, data: TargetUpdate):
    with get_session() as session:
        target = session.get(MediaServerTarget, target_id)
        if not target:
            raise HTTPException(404, "Integration not found")
        for key, value in data.model_dump(exclude={"api_key"}).items():
            setattr(target, key, value)
        if data.api_key:
            target.secret_ciphertext = Fernet(_key()).encrypt(data.api_key.encode()).decode()
        session.commit()
        return _serialize(target)


@router.delete("/integrations/{target_id}", status_code=204)
def delete_target(target_id: int):
    with get_session() as session:
        target = session.get(MediaServerTarget, target_id)
        if not target:
            raise HTTPException(404, "Integration not found")
        if (session.scalar(select(MediaServerExport.id).where(MediaServerExport.target_id == target_id)) or
            session.scalar(select(IntegrationUserMapping.id).where(IntegrationUserMapping.target_id == target_id)) or
            session.scalar(select(FeedSubscription.id).where(FeedSubscription.integration_target_id == target_id))):
            raise HTTPException(409, "This integration has export history; disable it instead")
        session.delete(target)
        session.commit()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Media-server redirect refused")


def _request(target: MediaServerTarget, method: str, path: str,
             payload: dict | None = None, *, token_override: str | None = None) -> bytes:
    if not path.startswith("/"):
        raise ValueError("Invalid media-server API path")
    headers = {"Accept": "application/json"}
    token = token_override if token_override is not None else _token(target)
    if target.kind == "plex":
        headers["X-Plex-Token"] = token
        headers["Accept"] = "application/xml"
    elif target.kind == "jellyfin":
        headers["X-Emby-Token"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = UpstreamRequest(f"{target.base_url}{path}", headers=headers, method=method,
        data=json.dumps(payload).encode() if payload is not None else None)
    with build_opener(_NoRedirect()).open(request, timeout=10) as response:
        return response.read(2 * 1024 * 1024)


def _mapped_path(target: MediaServerTarget, path: str) -> str:
    try:
        relative = Path(path).resolve().relative_to(Path(target.local_prefix).resolve())
    except ValueError as exc:
        raise ValueError("The published file is outside the integration's path mapping") from exc
    return posixpath.join(target.server_prefix, *relative.parts)


def discover(target: MediaServerTarget) -> dict:
    """Check the selected library and expose the server's actual library mode."""
    if target.kind == "plex":
        root = ElementTree.fromstring(_request(target, "GET", "/library/sections"))
        section = next((node for node in root.findall(".//Directory")
                        if node.attrib.get("key") == target.library_id), None)
        if section is None:
            raise ValueError("Plex library section not found")
        identity = ElementTree.fromstring(_request(target, "GET", "/identity"))
        machine_id = identity.attrib.get("machineIdentifier", "")
        if not re.fullmatch(r"[a-zA-Z0-9]{16,80}", machine_id):
            raise ValueError("Plex server identity is unavailable")
        scanner, agent = section.attrib.get("scanner", ""), section.attrib.get("agent", "")
        if "nfo" in agent.casefold():
            presentation = "nfo"
        elif "personal" in agent.casefold() or scanner == "Plex Video Files Scanner":
            presentation = "personal_media"
        elif "plex" in scanner.casefold() or "plex" in agent.casefold():
            presentation = "local_assets"
        else:
            presentation = "filename"
        return {"library": section.attrib.get("title"), "scanner": section.attrib.get("scanner"),
                "agent": section.attrib.get("agent"), "type": section.attrib.get("type"),
                "machine_id": machine_id, "presentation": presentation}
    if target.kind == "jellyfin":
        info = json.loads(_request(target, "GET", "/System/Info"))
        library = json.loads(_request(target, "GET", f"/Items/{quote(target.library_id, safe='')}"))
        if not library.get("Id"):
            raise ValueError("Jellyfin library not found")
        return {"server": info.get("ServerName"), "version": info.get("Version"),
                "library": library.get("Name")}
    libraries = json.loads(_request(target, "GET", "/api/libraries"))["libraries"]
    library = next((entry for entry in libraries if entry.get("id") == target.library_id), None)
    if not library:
        raise ValueError("Audiobookshelf library not found")
    if library.get("mediaType") != "podcast":
        raise ValueError("Choose an Audiobookshelf podcast library for Collection audio")
    return {"library": library.get("name"), "type": library.get("mediaType")}


@router.post("/integrations/{target_id}/test")
def test_target(target_id: int):
    with get_session() as session:
        target = session.get(MediaServerTarget, target_id)
        if not target:
            raise HTTPException(404, "Integration not found")
        try:
            return discover(target)
        except Exception as exc:
            logger.warning("Media server %s connection failed", target_id, exc_info=True)
            raise HTTPException(502, "Cannot reach the selected media-server library") from exc


def _write_nfo(path: Path, item: MediaItem, export: MediaServerExport,
               collection_title: str | None = None) -> None:
    kind = "movie" if item.kind in ("movie", "movie_extra") else "episodedetails"
    root = ElementTree.Element(kind)
    ElementTree.SubElement(root, "title").text = item.user_title or item.title
    ElementTree.SubElement(root, "plot").text = item.user_description or item.description or ""
    ElementTree.SubElement(root, "uniqueid", type="vodloft").text = str(item.id)
    if item.published_at:
        ElementTree.SubElement(root, "year").text = str(item.published_at.year)
        ElementTree.SubElement(root, "aired").text = item.published_at.date().isoformat()
    if item.duration:
        ElementTree.SubElement(root, "runtime").text = str(round(item.duration / 60))
    if collection_title and kind == "episodedetails":
        ElementTree.SubElement(root, "showtitle").text = collection_title
        if export.season_number is not None:
            ElementTree.SubElement(root, "season").text = str(export.season_number)
        if export.episode_number is not None:
            ElementTree.SubElement(root, "episode").text = str(export.episode_number)
    data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".nfo-", delete=False) as output:
        output.write(data)
        temporary = Path(output.name)
    os.replace(temporary, path.with_suffix(".nfo"))


def _write_artwork(path: Path, item: MediaItem, source_id: str | None) -> None:
    """Keep a validated local image beside the exported file for Jellyfin."""
    if not item.artwork_url or not source_id:
        return
    try:
        result = SourceGateway().call(source_id, "stream_fetch", timeout=35,
            url=item.artwork_url, headers={})
        body = base64.b64decode(result["data"], validate=True)
        image_type = result["content_type"].split(";", 1)[0].lower()
        if image_type == "image/jpeg" and body.startswith(b"\xff\xd8\xff"):
            extension = ".jpg"
        elif image_type == "image/png" and body.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = ".png"
        elif image_type == "image/webp" and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
            extension = ".webp"
        else:
            raise ValueError("Unsupported artwork representation")
        destination = path.with_name(path.stem + ("-poster" if item.kind == "movie" else "-thumb") + extension)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".artwork-", delete=False) as output:
            output.write(body)
            temporary = Path(output.name)
        os.replace(temporary, destination)
    except Exception:
        # Artwork is optional; discovery and the media file remain usable.
        logger.warning("Could not prepare artwork for media item %s", item.id)


def _presentation_numbers(session, item_id: int) -> tuple[int | None, int | None]:
    entry = session.scalar(select(CollectionEntry).where(CollectionEntry.item_id == item_id)
        .order_by(CollectionEntry.id))
    if not entry:
        return None, None
    season_match = re.search(r"\d+", entry.group or "")
    season = int(season_match.group()) if season_match else 1
    episode = (int(entry.episode_number) if entry.episode_number and
        entry.episode_number.isdecimal() else entry.position)
    return season, episode


def _find_remote(target: MediaServerTarget, server_path: str) -> str | None:
    if target.kind == "plex":
        for page in range(20):
            root = ElementTree.fromstring(_request(target, "GET",
                f"/library/sections/{quote(target.library_id, safe='')}/all?X-Plex-Container-Size=200&X-Plex-Container-Start={page * 200}"))
            media_items = [*root.findall(".//Video"), *root.findall(".//Track")]
            for media in media_items:
                if any(part.attrib.get("file") == server_path for part in media.findall(".//Part")):
                    return media.attrib.get("ratingKey")
            if len(media_items) < 200 or page * 200 + len(media_items) >= int(root.attrib.get("totalSize", 1000000)):
                break
        return None
    if target.kind == "jellyfin":
        for page in range(20):
            results = json.loads(_request(target, "GET", "/Items?Recursive=true&Limit=200&"
                f"StartIndex={page * 200}&Fields=Path&ParentId={quote(target.library_id, safe='')}"))
            items = results.get("Items", [])
            for item in items:
                if item.get("Path") == server_path:
                    return str(item.get("Id"))
            if len(items) < 200 or page * 200 + len(items) >= results.get("TotalRecordCount", 1000000):
                break
        return None
    for page in range(20):
        results = json.loads(_request(target, "GET", f"/api/libraries/{quote(target.library_id, safe='')}/items?limit=200&page={page}"))
        items = results.get("results", [])
        for item in items:
            if item.get("path") == server_path or any(f.get("metadata", {}).get("path") == server_path
                for f in item.get("media", {}).get("audioFiles", [])) or any(
                episode.get("audioFile", {}).get("metadata", {}).get("path") == server_path
                for episode in item.get("media", {}).get("episodes", [])):
                return str(item.get("id"))
        if len(items) < 200 or page * 200 + len(items) >= results.get("total", 1000000):
            break
    return None


def _find_abs_episode(target: MediaServerTarget, remote_id: str, server_path: str) -> str | None:
    item = json.loads(_request(target, "GET", f"/api/items/{quote(remote_id, safe='')}?expanded=1"))
    for episode in item.get("media", {}).get("episodes", []):
        if episode.get("audioFile", {}).get("metadata", {}).get("path") == server_path:
            return str(episode["id"])
    return None


def scan_export(export_id: int) -> None:
    with get_session() as session:
        export = session.get(MediaServerExport, export_id)
        target = session.get(MediaServerTarget, export.target_id)
        placement = session.get(ArtifactPlacement, export.placement_id)
        artifact = session.get(Artifact, placement.artifact_id)
        item = session.get(MediaItem, artifact.item_id)
        if not target.enabled or not Path(placement.path).is_file():
            export.state, export.error = "unavailable", "Target disabled or published file missing"
            session.commit()
            return
        try:
            server_path = _mapped_path(target, placement.path)
            if export.attempts == 0 or target.kind == "plex" and not export.presentation_strategy:
                capabilities = discover(target)
                if target.kind == "jellyfin":
                    membership = session.scalar(select(CollectionEntry).where(
                        CollectionEntry.item_id == item.id).order_by(CollectionEntry.id))
                    collection = session.get(MediaItem, membership.collection_id) if membership else None
                    _write_nfo(Path(placement.path), item, export,
                        collection.user_title or collection.title if collection else None)
                    reference = session.scalar(select(SourceReference).where(
                        SourceReference.item_id == item.id).order_by(SourceReference.id))
                    _write_artwork(Path(placement.path), item, reference.source_id if reference else None)
                    _request(target, "POST", "/Library/Refresh")
                elif target.kind == "plex":
                    export.remote_server_id = capabilities["machine_id"]
                    export.presentation_strategy = capabilities["presentation"]
                    if export.presentation_strategy == "nfo":
                        membership = session.scalar(select(CollectionEntry).where(
                            CollectionEntry.item_id == item.id).order_by(CollectionEntry.id))
                        collection = session.get(MediaItem, membership.collection_id) if membership else None
                        _write_nfo(Path(placement.path), item, export,
                            collection.user_title or collection.title if collection else None)
                    if export.presentation_strategy in {"nfo", "personal_media", "local_assets"}:
                        reference = session.scalar(select(SourceReference).where(
                            SourceReference.item_id == item.id).order_by(SourceReference.id))
                        _write_artwork(Path(placement.path), item, reference.source_id if reference else None)
                    _request(target, "POST", f"/library/sections/{quote(target.library_id, safe='')}/refresh")
                else:
                    if Path(placement.path).suffix.lower() not in {".mp3", ".m4a", ".aac"}:
                        raise ValueError("Audiobookshelf podcast export requires audio")
                    _request(target, "POST", f"/api/libraries/{quote(target.library_id, safe='')}/scan")
            remote_id = _find_remote(target, server_path)
            export.remote_id = remote_id
            if target.kind == "audiobookshelf" and remote_id:
                export.remote_episode_id = _find_abs_episode(target, remote_id, server_path)
            export.state = ("available" if remote_id and
                (target.kind != "audiobookshelf" or export.remote_episode_id) else "scanning")
            export.error = None
        except Exception:
            logger.exception("Media server export %s failed", export_id)
            export.state, export.error = "failed", "Delivery scan or verification failed"
        export.attempts += 1
        session.commit()


def dispatch_exports(profile_id: int, placement_id: int) -> None:
    with get_session() as session:
        profile = session.get(DomainLocalMediaProfile, profile_id)
        ids = []
        for target_id in profile.delivery_target_ids:
            if not (target := session.get(MediaServerTarget, target_id)) or not target.enabled:
                continue
            export = session.scalar(select(MediaServerExport).where(
                MediaServerExport.placement_id == placement_id, MediaServerExport.target_id == target_id))
            if not export:
                artifact = session.get(Artifact, session.get(ArtifactPlacement, placement_id).artifact_id)
                season, episode = _presentation_numbers(session, artifact.item_id)
                export = MediaServerExport(placement_id=placement_id, target_id=target_id,
                    state="pending", attempts=0, season_number=season, episode_number=episode)
                session.add(export)
                session.flush()
            ids.append(export.id)
        session.commit()
    for export_id in ids:
        threading.Thread(target=scan_export, args=(export_id,), daemon=True,
                         name=f"vodloft-export-{export_id}").start()


@router.get("/integrations/exports")
def exports():
    with get_session() as session:
        return [{"id": e.id, "target_id": e.target_id, "placement_id": e.placement_id,
            "state": e.state, "remote_id": e.remote_id,
            "remote_episode_id": e.remote_episode_id,
            "remote_server_id": e.remote_server_id,
            "presentation_strategy": e.presentation_strategy,
            "season_number": e.season_number, "episode_number": e.episode_number,
            "error": e.error,
            "attempts": e.attempts} for e in session.scalars(select(MediaServerExport)).all()]


def _external_url(target: MediaServerTarget, export: MediaServerExport) -> str:
    # Item links use the stored server ID, never the local filename or API key.
    identifier = quote(export.remote_id or "", safe="")
    if target.kind == "jellyfin":
        return f"{target.base_url}/web/#/details?id={identifier}"
    if target.kind == "audiobookshelf":
        return f"{target.base_url}/item/{identifier}"
    if export.remote_server_id:
        key = quote(f"/library/metadata/{export.remote_id}", safe="")
        return f"{target.base_url}/web/index.html#!/server/{export.remote_server_id}/details?key={key}"
    return f"{target.base_url}/web/index.html"


@router.get("/library/{item_id}/integrations")
def item_integrations(item_id: int, request: Request):
    with get_session() as session:
        if not session.get(MediaItem, item_id):
            raise HTTPException(404, "Media item not found")
        exports = session.scalars(select(MediaServerExport).join(ArtifactPlacement,
            MediaServerExport.placement_id == ArtifactPlacement.id).join(Artifact,
            ArtifactPlacement.artifact_id == Artifact.id).where(Artifact.item_id == item_id)).all()
        result = [{"id": export.id, "kind": target.kind, "name": target.name,
            "state": export.state, "remote_id": export.remote_id,
            "remote_episode_id": export.remote_episode_id,
            "presentation_strategy": export.presentation_strategy,
            "progress_path": f"/integrations/exports/{export.id}/progress/pull",
            "url": _external_url(target, export) if export.state == "available" else None}
            for export in exports if (target := session.get(MediaServerTarget, export.target_id))
            and principal(request).can_use_target(target.id)]
        for row in session.scalars(select(IntegrationFeedItem).where(IntegrationFeedItem.item_id == item_id)).all():
            delivery = session.get(IntegrationFeedDelivery, row.delivery_id)
            target = session.get(MediaServerTarget, delivery.target_id)
            if not principal(request).can_use_target(target.id):
                continue
            available = row.available and target.enabled and delivery.state == "subscribed"
            result.append({"id": row.id, "kind": target.kind, "name": target.name,
                "state": "available" if available else "unavailable", "remote_id": delivery.remote_id,
                "remote_episode_id": row.remote_episode_id, "presentation_strategy": "rss_pull",
                "progress_path": f"/integrations/rss-items/{row.id}/progress/pull",
                "url": f"{target.base_url}/item/{quote(delivery.remote_id, safe='')}" if available else None})
        return result


@router.post("/integrations/exports/{export_id}/progress/pull")
def pull_abs_progress(export_id: int, request: Request):
    """Explicit per-user import only advances local progress for a verified episode."""
    with get_session() as session:
        export = session.get(MediaServerExport, export_id)
        target = session.get(MediaServerTarget, export.target_id) if export else None
        if not target or target.kind != "audiobookshelf" or export.state != "available" or not export.remote_episode_id:
            raise HTTPException(409, "A verified Audiobookshelf podcast episode is required")
        placement = session.get(ArtifactPlacement, export.placement_id)
        artifact = session.get(Artifact, placement.artifact_id)
        return _import_abs_progress(session, target, artifact.item_id, export.remote_id, export.remote_episode_id, request)



@router.post("/integrations/exports/{export_id}/retry")
def retry_export(export_id: int):
    with get_session() as session:
        export = session.get(MediaServerExport, export_id)
        if not export:
            raise HTTPException(404, "Export not found")
        export.attempts = 0
        session.commit()
    threading.Thread(target=scan_export, args=(export_id,), daemon=True).start()
    return {"id": export_id, "state": "pending"}


def reconcile_exports() -> None:
    with get_session() as session:
        ids = [e.id for e in session.scalars(select(MediaServerExport).where(
            MediaServerExport.state.in_(["pending", "scanning", "failed"]),
            MediaServerExport.attempts < 10)).all()]
    for export_id in ids:
        scan_export(export_id)


class UserMappingInput(BaseModel):
    user_key: str = Field(default="admin", min_length=1, max_length=80)
    remote_user_id: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, max_length=16384)


class UserMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_id: int
    user_key: str
    remote_user_id: str


def _permitted_target(session, target_id: int, request: Request) -> MediaServerTarget:
    target = session.get(MediaServerTarget, target_id)
    if not target or not target.enabled or not principal(request).can_use_target(target_id):
        raise HTTPException(404, "Enabled media-server connection not found")
    if target.kind != "audiobookshelf":
        raise HTTPException(422, "Select an Audiobookshelf connection")
    return target


@router.get("/integrations/{target_id}/users", response_model=list[UserMappingResponse])
def mapped_users(target_id: int, request: Request):
    with get_session() as session:
        _permitted_target(session, target_id, request)
        query = select(IntegrationUserMapping).where(IntegrationUserMapping.target_id == target_id)
        if principal(request).role != "admin":
            query = query.where(IntegrationUserMapping.user_key == principal(request).key)
        return [UserMappingResponse.model_validate(row) for row in session.scalars(query).all()]


@router.put("/integrations/{target_id}/users", response_model=UserMappingResponse)
def map_user(target_id: int, data: UserMappingInput, request: Request):
    actor = principal(request)
    if actor.role != "admin" and data.user_key != actor.key:
        raise HTTPException(403, "You can map only your own listening account")
    with get_session() as session:
        target = _permitted_target(session, target_id, request)
        user = session.get(LocalUser, data.user_key) if data.user_key != "admin" else None
        if data.user_key != "admin" and (not user or not user.enabled or target_id not in user.target_ids):
            raise HTTPException(422, "Choose an enabled local account with access to this media server")
        try:
            identity = json.loads(_request(target, "GET", "/api/me", token_override=data.api_key))
        except Exception as exc:
            raise HTTPException(502, "Could not verify the Audiobookshelf listening account") from exc
        if identity.get("id") != data.remote_user_id or identity.get("isActive") is False or identity.get("isLocked"):
            raise HTTPException(422, "The token does not identify the selected active Audiobookshelf user")
        mapping = session.scalar(select(IntegrationUserMapping).where(
            IntegrationUserMapping.target_id == target_id, IntegrationUserMapping.user_key == data.user_key))
        if not mapping:
            mapping = IntegrationUserMapping(target_id=target_id, user_key=data.user_key)
            session.add(mapping)
        mapping.remote_user_id = data.remote_user_id
        mapping.secret_ciphertext = Fernet(_key()).encrypt(data.api_key.encode()).decode()
        session.commit()
        return UserMappingResponse.model_validate(mapping)


@router.delete("/integrations/{target_id}/users/{user_key}", status_code=204)
def unmap_user(target_id: int, user_key: str, request: Request):
    if principal(request).role != "admin" and principal(request).key != user_key:
        raise HTTPException(403, "You can unlink only your own listening account")
    with get_session() as session:
        _permitted_target(session, target_id, request)
        mapping = session.scalar(select(IntegrationUserMapping).where(
            IntegrationUserMapping.target_id == target_id, IntegrationUserMapping.user_key == user_key))
        if not mapping:
            raise HTTPException(404, "Listening account mapping not found")
        session.delete(mapping); session.commit()


class RemoteProgress(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    currentTime: float = Field(default=0, ge=0, le=315360000)
    isFinished: bool = False


def _import_abs_progress(session, target, item_id, remote_id, episode_id, request):
    actor = principal(request)
    _permitted_target(session, target.id, request)
    mapping = session.scalar(select(IntegrationUserMapping).where(
        IntegrationUserMapping.target_id == target.id, IntegrationUserMapping.user_key == actor.key))
    if not mapping:
        raise HTTPException(409, "Map your Audiobookshelf listening account before importing progress")
    token = Fernet(_key()).decrypt(mapping.secret_ciphertext.encode()).decode()
    try:
        identity = json.loads(_request(target, "GET", "/api/me", token_override=token))
        if identity.get("id") != mapping.remote_user_id or identity.get("isActive") is False or identity.get("isLocked"):
            raise ValueError("Listening identity changed")
        remote = RemoteProgress.model_validate_json(_request(target, "GET", "/api/me/progress/" +
            quote(remote_id, safe="") + "/" + quote(episode_id, safe=""), token_override=token))
    except Exception as exc:
        raise HTTPException(502, "Could not verify and read Audiobookshelf progress") from exc
    progress = session.scalar(select(PlaybackProgress).where(
        PlaybackProgress.user_key == actor.key, PlaybackProgress.item_id == item_id))
    if not progress:
        progress = PlaybackProgress(user_key=actor.key, item_id=item_id, seconds=0, completed=False)
        session.add(progress)
    progress.seconds = max(progress.seconds, remote.currentTime)
    progress.completed = progress.completed or remote.isFinished
    session.commit()
    return {"seconds": progress.seconds, "completed": progress.completed}


class FeedDeliveryInput(BaseModel):
    target_id: int
    stream_profile_id: int
    folder_id: str = Field(min_length=1, max_length=120)
    server_path: str = Field(min_length=1, max_length=2000)
    vodloft_url: str = Field(min_length=1, max_length=2000)

    @field_validator('server_path')
    @classmethod
    def absolute_path(cls, value):
        return TargetInput.absolute_mapping(value)

    @field_validator('vodloft_url')
    @classmethod
    def application_url(cls, value):
        return TargetInput.server_url(value)


class FeedDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_id: int
    subscription_id: int
    folder_id: str
    server_path: str
    remote_id: str | None
    state: str
    error: str | None
    attempts: int
    last_checked_at: datetime | None


@router.get('/integrations/rss', response_model=list[FeedDeliveryResponse])
def feed_deliveries(request: Request):
    with get_session() as session:
        return [FeedDeliveryResponse.model_validate(row) for row in session.scalars(select(IntegrationFeedDelivery)).all()
            if principal(request).can_use_target(row.target_id)]


@router.post('/integrations/rss', response_model=FeedDeliveryResponse, status_code=201)
def add_feed_delivery(data: FeedDeliveryInput, request: Request, background: BackgroundTasks):
    """VodLoft owns the feed; ABS owns the copies it downloads and their retention."""
    with get_session() as session:
        target = _permitted_target(session, data.target_id, request)
        profile = session.get(CollectionStreamProfile, data.stream_profile_id)
        if not profile or not profile.enabled or profile.format != 'audio':
            raise HTTPException(422, 'Select an enabled audio Stream Profile')
        if not Path(data.server_path).is_relative_to(target.server_prefix) or data.server_path == target.server_prefix:
            raise HTTPException(422, 'Choose a podcast subfolder inside the configured server folder')
        subscription = session.scalar(select(FeedSubscription).where(
            FeedSubscription.stream_profile_id == profile.id,
            FeedSubscription.integration_target_id == target.id))
        if subscription:
            raise HTTPException(409, 'This Stream Profile already has an RSS delivery to this server')
        subscription = FeedSubscription(collection_id=profile.collection_id, stream_profile_id=profile.id,
            user_key=f'integration:{target.id}', integration_target_id=target.id, token=secrets.token_urlsafe(32))
        session.add(subscription); session.flush()
        delivery = IntegrationFeedDelivery(target_id=target.id, subscription_id=subscription.id,
            folder_id=data.folder_id, server_path=data.server_path,
            feed_url=f'{data.vodloft_url}/feeds/vodloft/{subscription.token}.xml')
        session.add(delivery); session.commit()
        result = FeedDeliveryResponse.model_validate(delivery)
        background.add_task(reconcile_feed_delivery, delivery.id)
        return result


_rss_lock = threading.RLock()


def reconcile_feed_delivery(delivery_id: int):
    # Match before creating, including after an interrupted response. A remote
    # podcast with a different feed is never taken over just because its path matches.
    with _rss_lock, get_session() as session:
        delivery = session.get(IntegrationFeedDelivery, delivery_id)
        if not delivery:
            return
        target = session.get(MediaServerTarget, delivery.target_id)
        subscription = session.get(FeedSubscription, delivery.subscription_id)
        profile = session.get(CollectionStreamProfile, subscription.stream_profile_id) if subscription else None
        delivery.last_checked_at = datetime.now(timezone.utc)
        if not target or not target.enabled or not profile or not profile.enabled:
            delivery.state, delivery.error = 'paused', 'Connection or Stream Profile is disabled'
            session.commit(); return
        delivery.attempts += 1
        session.commit()
        try:
            collection = session.get(MediaItem, profile.collection_id)
            if not delivery.remote_id:
                remote_id = _find_remote(target, delivery.server_path)
                if not remote_id:
                    remote = json.loads(_request(target, 'POST', '/api/podcasts', {
                        'libraryId': target.library_id, 'folderId': delivery.folder_id, 'path': delivery.server_path,
                        'media': {'metadata': {'title': collection.user_title or collection.title,
                            'description': collection.user_description or collection.description or '',
                            'feedUrl': delivery.feed_url}, 'autoDownloadEpisodes': True,
                            'autoDownloadSchedule': '*/15 * * * *'},
                    }))
                    remote_id = remote.get('id')
                    if not remote_id:
                        raise ValueError('Podcast creation did not return a remote identity')
                delivery.remote_id = str(remote_id)
                session.commit()
            remote = json.loads(_request(target, 'GET', f'/api/items/{quote(delivery.remote_id, safe="")}?expanded=1'))
            metadata = remote.get('media', {}).get('metadata', {})
            if (remote.get('libraryId') != target.library_id or remote.get('path') != delivery.server_path
                or remote.get('mediaType') != 'podcast' or metadata.get('feedUrl') != delivery.feed_url):
                raise ValueError('Podcast ownership or identity does not match this delivery')
            _request(target, 'GET', f'/api/podcasts/{quote(delivery.remote_id, safe="")}/checknew?limit=20')
            published = session.scalars(select(PublishedEntry).where(PublishedEntry.subscription_id == subscription.id)).all()
            by_url_path = {f'/feeds/vodloft/{subscription.token}/media/{entry.id}/{quote(Path(entry.path).name)}': entry for entry in published}
            # Keep downloaded availability separate from merely subscribing a podcast.
            for episode in remote.get('media', {}).get('episodes', []):
                enclosure_path = urlsplit(episode.get('enclosure', {}).get('url', '')).path
                entry = next((value for suffix, value in by_url_path.items() if enclosure_path.endswith(suffix)), None)
                if not entry or not episode.get('id'):
                    continue
                row = session.scalar(select(IntegrationFeedItem).where(
                    IntegrationFeedItem.delivery_id == delivery.id, IntegrationFeedItem.item_id == entry.item_id))
                if not row:
                    row = IntegrationFeedItem(delivery_id=delivery.id, item_id=entry.item_id)
                    session.add(row)
                row.remote_episode_id = str(episode['id'])
                row.available = bool(episode.get('audioFile')) and not remote.get('isMissing', False)
            present_ids = {str(episode.get('id')) for episode in remote.get('media', {}).get('episodes', [])}
            for row in session.scalars(select(IntegrationFeedItem).where(IntegrationFeedItem.delivery_id == delivery.id)).all():
                if row.remote_episode_id not in present_ids:
                    row.available = False
            delivery.state, delivery.error, delivery.attempts = 'subscribed', None, 0
        except Exception:
            # External failure affects delivery alone, with no Source credentials in diagnostics.
            delivery.state, delivery.error = 'failed', 'Audiobookshelf RSS delivery could not be verified or refreshed'
        session.commit()


@router.post('/integrations/rss/{delivery_id}/retry')
def retry_feed_delivery(delivery_id: int, background: BackgroundTasks):
    with get_session() as session:
        delivery = session.get(IntegrationFeedDelivery, delivery_id)
        if not delivery:
            raise HTTPException(404, 'RSS delivery not found')
        delivery.attempts, delivery.last_checked_at = 0, None
        session.commit()
    background.add_task(reconcile_feed_delivery, delivery_id)
    return {'id': delivery_id, 'state': 'pending'}


@router.delete('/integrations/rss/{delivery_id}', status_code=204)
def remove_feed_delivery(delivery_id: int):
    from backend.api.endpoints.vodloft.feeds import _remove_published
    with get_session() as session:
        delivery = session.get(IntegrationFeedDelivery, delivery_id)
        if not delivery:
            raise HTTPException(404, 'RSS delivery not found')
        subscription_id = delivery.subscription_id
        session.delete(session.get(FeedSubscription, subscription_id)); session.commit()
    _remove_published(subscription_id)
    # ABS owns its downloaded files; retiring a feed never deletes those files.


@router.post('/integrations/rss-items/{mapping_id}/progress/pull')
def pull_feed_progress(mapping_id: int, request: Request):
    with get_session() as session:
        row = session.get(IntegrationFeedItem, mapping_id)
        delivery = session.get(IntegrationFeedDelivery, row.delivery_id) if row else None
        if not delivery or not row.available or delivery.state != 'subscribed':
            raise HTTPException(409, 'A verified downloaded Audiobookshelf episode is required')
        target = _permitted_target(session, delivery.target_id, request)
        return _import_abs_progress(session, target, row.item_id, delivery.remote_id, row.remote_episode_id, request)


def reconcile_feed_deliveries():
    with get_session() as session:
        now = datetime.now(timezone.utc)
        due = [row.id for row in session.scalars(select(IntegrationFeedDelivery)).all()
            if not row.last_checked_at or now - row.last_checked_at.replace(tzinfo=timezone.utc) >=
                timedelta(seconds=900 if row.state == 'subscribed' else min(3600, 60 * 2 ** min(row.attempts, 6)))]
    for delivery_id in due:
        reconcile_feed_delivery(delivery_id)
