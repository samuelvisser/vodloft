from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Settings


def ytdlp_source_options(session: Session) -> str:
    """Your own yt-dlp options for every download of the yt-dlp Source."""
    text = session.scalars(select(Settings.ytdlp_options).order_by(Settings.id).limit(1)).first()
    return text or ""


def save_ytdlp_source_options(session: Session, text: str) -> str:
    row = session.scalars(select(Settings).order_by(Settings.id).limit(1)).first()
    if row is None:
        row = Settings()
        session.add(row)
    row.ytdlp_options = text
    session.flush()
    return row.ytdlp_options
