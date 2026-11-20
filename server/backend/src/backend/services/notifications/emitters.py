"""Telling messages and actions what happened, from the places where it happens.

Each one records the event in the caller's transaction, so it is only sent once that is committed.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session


from backend.types.collection_contracts import collection_contract
from backend.types.collection_types import CollectionType
from backend.db.models import Creator, CreatorSection, Collection, CollectionList, DownloadProfile, Episode, User

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


def creator_sections_found(session: Session, creator: Creator, sections: list[CreatorSection]) -> None:
    """The daily look found sections of a creator that wait for a choice: add them, or ignore them."""
    from backend.services.creators import creator_names

    if not sections:
        return
    names = ", ".join(section.title for section in sections[:3]) + (f" and {len(sections) - 3} more" if len(sections) > 3 else "")
    # In the Site's words, such as "album", or "albums and playlists" for several types.
    from backend.services.creators import account_site
    from backend.services.sites import joined_names

    names_of = joined_names(account_site(section.account).section_type_of(section).names for section in sections)
    what = names_of.singular if len(sections) == 1 else names_of.plural
    emit(
        session, Event.CREATOR_SECTIONS_FOUND,
        title=f"New {what} on {creator.title}" if len(sections) == 1 else f"{len(sections)} new {what} on {creator.title}",
        body=f"{names}. Choose on the {creator_names(creator).singular}'s page whether to add {'it' if len(sections) == 1 else 'them'}.",
        url=f"/edit-creator/{creator.slug}", data={"creator": creator.title, "sections": [section.title for section in sections]},
        dedupe_key=f"creator-sections:{creator.id}:{','.join(sorted(section.ref for section in sections))}",
    )


def link_seasons_found(session: Session, collection: Collection, playlists: list[CollectionList]) -> None:
    """A collection whose selected playlists are seasons found playlists that wait for the user's choice."""
    if not playlists:
        return
    names = ", ".join(playlist.title for playlist in playlists[:3]) + (f" and {len(playlists) - 3} more" if len(playlists) > 3 else "")
    one = len(playlists) == 1
    season = collection_contract(collection.type).words.season
    # The Site's own word for what it found, such as playlist on YouTube or album on Bandcamp.
    from backend.services.link_seasons import list_names
    lists = list_names(collection)
    emit(
        session, Event.CREATOR_SECTIONS_FOUND,
        title=f"New {lists.singular} for {collection.title}" if one else f"{len(playlists)} new {lists.plural} for {collection.title}",
        body=f"{names}. Choose in the collection's {season.plural} whether {f'it becomes {season.a}' if one else f'they become {season.plural}'}.",
        url=f"/edit-collection/{collection.id}?seasons=1",
        data={"collection": collection.title, "playlists": [playlist.title for playlist in playlists]},
        dedupe_key=f"collection-playlists:{collection.id}:{','.join(sorted(playlist.ref for playlist in playlists))}",
    )
