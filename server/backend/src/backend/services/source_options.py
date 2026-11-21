from __future__ import annotations

from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.core import get_session
from backend.db.models import Settings
from sources import Source, get_source
from sources.contract import Feature
from sources.ytdlp_options import call_options, every_call_arguments


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


def ytdlp_call_arguments(session: Session, source: Source | str, collection_options: str | None = None) -> tuple[str, ...]:
    """The network and site options of the Source's and the collection's own yt-dlp options.

    These reach every yt-dlp call, not only downloads: a proxy or a site's extractor arguments are
    needed to find a collection's videos as much as to download them.
    """
    if not (get_source(source) if isinstance(source, str) else source).has(Feature.YTDLP_OPTIONS):
        return ()
    texts = (ytdlp_source_options(session), collection_options or "")
    return tuple(argument for text in texts for argument in every_call_arguments(text))


def ytdlp_call_options(
    source: Source | str, collection_options: str | None = None, *, session: Session | None = None,
) -> AbstractContextManager[None]:
    """yt-dlp calls in the returned block use the Source's and the collection's network and site options.

    The options are read right away, so a caller can close its transaction before the slow calls.
    """
    if session is not None:
        return call_options(ytdlp_call_arguments(session, source, collection_options))
    with get_session() as own:
        return call_options(ytdlp_call_arguments(own, source, collection_options))
