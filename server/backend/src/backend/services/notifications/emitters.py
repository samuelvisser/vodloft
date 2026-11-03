"""Telling messages and actions what happened, from the places where it happens.

Each one records the event in the caller's transaction, so it is only sent once that is committed.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import Collection, DownloadProfile, Episode, User

from .events import Event, emit


def _episode_url(episode: Episode) -> str:
    return f"/collection/{episode.collection.slug}/episode/{episode.slug}"


def _file_data(episode: Episode, path: str | None) -> dict:
    return {
        "collection": episode.collection.title, "episode": episode.title, "filePath": path or None,
        "folder": str(Path(path).parent) if path else None,
    }


def episode_downloaded(session: Session, episode: Episode, *, path: str, replaced: bool) -> None:
    """A download finished: a new one, or a better version that replaced the old file."""
    collection = episode.collection
    emit(
        session, Event.EPISODE_REPLACED if replaced else Event.EPISODE_DOWNLOADED,
        title=f"{'Replaced' if replaced else 'Downloaded'}: {episode.title}", body=collection.title,
        collection_id=collection.id, url=_episode_url(episode), data=_file_data(episode, path),
    )


def episode_deleted(session: Session, episode: Episode, *, path: str | None, reason: str) -> None:
    """A download's file was removed, by hand or because it fell outside its profile's limit."""
    collection = episode.collection
    emit(
        session, Event.EPISODE_DELETED, title=f"Deleted: {episode.title}", body=f"{collection.title}. {reason}",
        collection_id=collection.id, url=_episode_url(episode), data=_file_data(episode, path),
    )


def new_episodes_found(session: Session, collection: Collection, count: int) -> None:
    """New episodes in a Collection that downloads nothing by itself.

    The first look at a new Collection finds every episode, which is not news.
    """
    if count <= 0:
        return
    downloads = session.scalar(select(DownloadProfile.id).where(
        DownloadProfile.collection_id == collection.id, DownloadProfile.enable_profile.is_(True),
    ).limit(1))
    if downloads is not None:
        return
    episodes = session.scalar(select(func.count(Episode.id)).where(Episode.collection_id == collection.id)) or 0
    if episodes <= count:
        return
    emit(
        session, Event.NEW_EPISODES,
        title=f"{count} new episode{'s' if count != 1 else ''} in {collection.title}",
        body="Nothing downloads them automatically.", collection_id=collection.id,
        url=f"/collection/{collection.slug}", data={"collection": collection.title},
    )


def quick_download_finished(session: Session, *, owner: str | None, title: str) -> None:
    """A Quick download is ready to save. It belongs to whoever asked for it."""
    user_id = session.scalar(select(User.id).where(User.username == owner)) if owner else None
    emit(
        session, Event.QUICK_DOWNLOAD_FINISHED, title=f"Ready to save: {title}",
        body="Your Quick download finished.", user_id=user_id, url="/quick-download",
    )
