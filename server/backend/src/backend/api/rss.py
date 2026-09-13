from __future__ import annotations

import mimetypes
from datetime import datetime, time, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db import get_session
from backend.db.models import Collection, MediaDownload, Video
from backend.security import ensure_application_settings, valid_rss_token

router = APIRouter(prefix="/rss", tags=["rss"])


def _authorize(session: Session, token: str | None):
    settings = ensure_application_settings(session)
    if not valid_rss_token(token, settings):
        raise HTTPException(status_code=401, detail="Invalid RSS token")
    return settings


def _date(video: Video) -> str | None:
    if video.upload_date is None:
        return None
    value = datetime.combine(video.upload_date, time.min, tzinfo=timezone.utc)
    return format_datetime(value)


def _xml_response(root: ET.Element) -> Response:
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=body, media_type="application/rss+xml; charset=utf-8")


def _base_channel(title: str, link: str, description: str | None) -> tuple[ET.Element, ET.Element]:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = link
    ET.SubElement(channel, "description").text = description or title
    ET.SubElement(channel, "generator").text = "VodLoft"
    return root, channel


def _add_video_item(channel: ET.Element, video: Video, request: Request, token: str) -> None:
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = video.title
    ET.SubElement(item, "link").text = video.source_url
    ET.SubElement(item, "guid", isPermaLink="false").text = f"{video.extractor}:{video.extractor_id}"
    if video.description:
        ET.SubElement(item, "description").text = video.description
    if published := _date(video):
        ET.SubElement(item, "pubDate").text = published
    artifact = next((entry for entry in video.media_downloads if entry.status == "downloaded" and entry.file_path), None)
    if artifact is not None:
        base = str(request.base_url).rstrip("/")
        url = f"{base}/api/rss/media/{artifact.id}?token={quote(token)}"
        attrs = {"url": url}
        if artifact.downloaded_bytes is not None:
            attrs["length"] = str(artifact.downloaded_bytes)
        content_type, _ = mimetypes.guess_type(artifact.file_path or "")
        attrs["type"] = content_type or "application/octet-stream"
        ET.SubElement(item, "enclosure", attrs)


@router.get("/collections/{collection_id}.xml")
def collection_feed(
    collection_id: int,
    request: Request,
    token: str = Query(...),
    session: Session = Depends(get_session),
):
    settings = _authorize(session, token)
    collection = session.scalar(
        select(Collection)
        .where(Collection.id == collection_id)
        .options(selectinload(Collection.videos).selectinload(Video.media_downloads))
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    root, channel = _base_channel(collection.title, collection.source_url, collection.description)
    videos = sorted(
        collection.videos,
        key=lambda video: (video.upload_date or datetime.min.date(), video.id),
        reverse=True,
    )[: settings.rss_item_limit or None]
    for video in videos:
        _add_video_item(channel, video, request, token)
    return _xml_response(root)


@router.get("/downloads.xml")
def downloads_feed(request: Request, token: str = Query(...), session: Session = Depends(get_session)):
    settings = _authorize(session, token)
    artifacts = list(
        session.scalars(
            select(MediaDownload)
            .where(MediaDownload.status == "downloaded")
            .options(selectinload(MediaDownload.video).selectinload(Video.media_downloads))
            .order_by(MediaDownload.downloaded_at.desc(), MediaDownload.id.desc())
            .limit(settings.rss_item_limit if settings.rss_item_limit > 0 else 1000000)
        )
    )
    root, channel = _base_channel("VodLoft downloads", str(request.base_url), "Recently downloaded media")
    seen: set[int] = set()
    for artifact in artifacts:
        if artifact.video_id in seen:
            continue
        seen.add(artifact.video_id)
        _add_video_item(channel, artifact.video, request, token)
    return _xml_response(root)


@router.get("/media/{media_download_id}")
def rss_media_file(media_download_id: int, token: str = Query(...), session: Session = Depends(get_session)):
    _authorize(session, token)
    artifact = session.get(MediaDownload, media_download_id)
    if artifact is None or artifact.status != "downloaded" or not artifact.file_path:
        raise HTTPException(status_code=404, detail="Downloaded media not found")
    path = Path(artifact.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Downloaded file is missing")
    return FileResponse(path, filename=path.name)
