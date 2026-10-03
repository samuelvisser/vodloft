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
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request as UpstreamRequest, build_opener
from xml.etree import ElementTree

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import (Artifact, ArtifactPlacement, CollectionEntry,
    MediaItem, MediaServerExport, MediaServerTarget, PlaybackProgress, SourceReference)
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


def _serialize(target: MediaServerTarget) -> dict:
    return {"id": target.id, "kind": target.kind, "name": target.name,
        "base_url": target.base_url, "library_id": target.library_id,
        "local_prefix": target.local_prefix, "server_prefix": target.server_prefix,
        "enabled": target.enabled}


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
def update_target(target_id: int, data: TargetInput):
    with get_session() as session:
        target = session.get(MediaServerTarget, target_id)
        if not target:
            raise HTTPException(404, "Integration not found")
        for key, value in data.model_dump(exclude={"api_key"}).items():
            setattr(target, key, value)
        target.secret_ciphertext = Fernet(_key()).encrypt(data.api_key.encode()).decode()
        session.commit()
        return _serialize(target)


@router.delete("/integrations/{target_id}", status_code=204)
def delete_target(target_id: int):
    with get_session() as session:
        target = session.get(MediaServerTarget, target_id)
        if not target:
            raise HTTPException(404, "Integration not found")
        if session.scalar(select(MediaServerExport.id).where(MediaServerExport.target_id == target_id)):
            raise HTTPException(409, "This integration has export history; disable it instead")
        session.delete(target)
        session.commit()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Media-server redirect refused")


def _request(target: MediaServerTarget, method: str, path: str,
             payload: dict | None = None) -> bytes:
    if not path.startswith("/"):
        raise ValueError("Invalid media-server API path")
    headers = {"Accept": "application/json"}
    token = _token(target)
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
        return [{"id": export.id, "kind": target.kind, "name": target.name,
            "state": export.state, "remote_id": export.remote_id,
            "remote_episode_id": export.remote_episode_id,
            "presentation_strategy": export.presentation_strategy,
            "url": _external_url(target, export) if export.state == "available" else None}
            for export in exports if (target := session.get(MediaServerTarget, export.target_id))
            and principal(request).can_use_target(target.id)]


@router.post("/integrations/exports/{export_id}/progress/pull")
def pull_abs_progress(export_id: int):
    """Explicit per-user import only advances local progress for a verified episode."""
    with get_session() as session:
        export = session.get(MediaServerExport, export_id)
        target = session.get(MediaServerTarget, export.target_id) if export else None
        if not target or target.kind != "audiobookshelf" or export.state != "available" or not export.remote_episode_id:
            raise HTTPException(409, "A verified Audiobookshelf podcast episode is required")
        placement = session.get(ArtifactPlacement, export.placement_id)
        artifact = session.get(Artifact, placement.artifact_id)
        try:
            remote = json.loads(_request(target, "GET", "/api/me/progress/" +
                quote(export.remote_id, safe="") + "/" + quote(export.remote_episode_id, safe="")))
        except Exception as exc:
            raise HTTPException(502, "Could not read Audiobookshelf progress") from exc
        seconds = max(0.0, float(remote.get("currentTime") or 0))
        progress = session.scalar(select(PlaybackProgress).where(
            PlaybackProgress.user_key == "admin", PlaybackProgress.item_id == artifact.item_id))
        if not progress:
            progress = PlaybackProgress(user_key="admin", item_id=artifact.item_id)
            session.add(progress)
        progress.seconds = max(progress.seconds, seconds)
        progress.completed = progress.completed or bool(remote.get("isFinished"))
        session.commit()
        return {"seconds": progress.seconds, "completed": progress.completed}


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
