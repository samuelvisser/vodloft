"""Delivery targets and verified media-server exports."""

import json
import logging
import os
import posixpath
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from backend.db import get_session
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import (Artifact, ArtifactPlacement, MediaItem,
    MediaServerExport, MediaServerTarget)
from backend.source_manager.runtime import runtime_root

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
def targets():
    with get_session() as session:
        return [_serialize(t) for t in session.scalars(select(MediaServerTarget)).all()]


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


def _request(target: MediaServerTarget, method: str, path: str) -> bytes:
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
    request = Request(f"{target.base_url}{path}", headers=headers, method=method)
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
        return {"library": section.attrib.get("title"), "scanner": section.attrib.get("scanner"),
                "agent": section.attrib.get("agent"), "type": section.attrib.get("type")}
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


def _write_nfo(path: Path, item: MediaItem) -> None:
    kind = "movie" if item.kind in ("movie", "movie_extra") else "episodedetails"
    root = ElementTree.Element(kind)
    ElementTree.SubElement(root, "title").text = item.user_title or item.title
    ElementTree.SubElement(root, "plot").text = item.description or ""
    ElementTree.SubElement(root, "uniqueid", type="vodloft").text = str(item.id)
    data = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".nfo-", delete=False) as output:
        output.write(data)
        temporary = Path(output.name)
    os.replace(temporary, path.with_suffix(".nfo"))


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
                for f in item.get("media", {}).get("audioFiles", [])):
                return str(item.get("id"))
        if len(items) < 200 or page * 200 + len(items) >= results.get("total", 1000000):
            break
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
            if export.attempts == 0:
                discover(target)
                if target.kind == "jellyfin":
                    _write_nfo(Path(placement.path), item)
                    _request(target, "POST", "/Library/Refresh")
                elif target.kind == "plex":
                    _request(target, "POST", f"/library/sections/{quote(target.library_id, safe='')}/refresh")
                else:
                    if Path(placement.path).suffix.lower() not in {".mp3", ".m4a", ".aac"}:
                        raise ValueError("Audiobookshelf podcast export requires audio")
                    _request(target, "POST", f"/api/libraries/{quote(target.library_id, safe='')}/scan")
            remote_id = _find_remote(target, server_path)
            export.remote_id = remote_id
            export.state = "available" if remote_id else "scanning"
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
                export = MediaServerExport(placement_id=placement_id, target_id=target_id,
                    state="pending", attempts=0)
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
            "state": e.state, "remote_id": e.remote_id, "error": e.error,
            "attempts": e.attempts} for e in session.scalars(select(MediaServerExport)).all()]


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
