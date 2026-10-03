"""Import WireLoft's local media into the normalized VodLoft library.

Revision ID: 8e5a2c9f41d0
Revises: 3c8f6a1d2b47
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func, select

from backend.db import get_session
from backend.db.models import Show
from backend.db.models.media_item import Episode, Movie, MovieExtra
from backend.db.models.vodloft import (Artifact, ArtifactPlacement, CollectionEntry,
    Domain, LegacyMediaLink, MediaDemand, MediaItem, MovieExtraParent, SourceDomain, SourceReference)
from config import get_settings

revision = "8e5a2c9f41d0"
down_revision = "3c8f6a1d2b47"
title = "Import existing WireLoft media into VodLoft"

_extensions = frozenset({".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".mov"})


def _domain(session) -> Domain:
    domain = session.scalar(select(Domain).where(Domain.hostname == "dailywire.com"))
    if not domain:
        domain = Domain(hostname="dailywire.com", display_name="The Daily Wire")
        session.add(domain)
        session.flush()
    if not session.scalar(select(SourceDomain).where(
            SourceDomain.domain_id == domain.id, SourceDomain.source_id == "dailywire")):
        session.add(SourceDomain(domain_id=domain.id, source_id="dailywire", support="verified"))
        session.flush()
    return domain


def _item(session, domain: Domain, legacy_type: str, legacy_id: int, kind: str,
          slug: str, title: str, url: str, description: str | None = None,
          duration: float | None = None, artwork: str | None = None) -> MediaItem:
    link = session.scalar(select(LegacyMediaLink).where(
        LegacyMediaLink.legacy_type == legacy_type, LegacyMediaLink.legacy_id == legacy_id))
    if link:
        return session.get(MediaItem, link.item_id)
    parts = urlsplit(url).path.strip('/').split('/')
    namespace = {'shows': 'show', 'episodes': 'episode', 'movies': 'videos', 'clip': 'clips'}.get(parts[0], parts[0])
    canonical = f'https://www.dailywire.com/{namespace}/{parts[1]}' if len(parts) == 2 else url
    reference = session.scalar(select(SourceReference).where(
        SourceReference.source_id == "dailywire", SourceReference.domain_id == domain.id,
        SourceReference.url.in_([url, canonical])))
    if reference:
        item = session.get(MediaItem, reference.item_id)
    else:
        item = MediaItem(domain_id=domain.id, kind=kind, title=title,
            description=description, duration=duration, artwork_url=artwork)
        session.add(item)
        session.flush()
    identity = session.scalar(select(SourceReference).where(
        SourceReference.source_id == "dailywire", SourceReference.domain_id == domain.id,
        SourceReference.namespace == legacy_type, SourceReference.upstream_id == slug,
        SourceReference.connection_key == 0))
    if not identity:
        session.add(SourceReference(item_id=item.id, domain_id=domain.id,
            source_id="dailywire", namespace=legacy_type, upstream_id=slug,
            url=url, connection_key=0))
    session.add(LegacyMediaLink(legacy_type=legacy_type, legacy_id=legacy_id, item_id=item.id))
    session.flush()
    return item


def _copy_downloads(session, item: MediaItem, downloads) -> None:
    root = Path(get_settings().download_settings.download_root).resolve()
    destination_root = root / "vodloft"
    destination_root.mkdir(parents=True, exist_ok=True)
    for download in downloads:
        if download.artifact_status != "available" or not download.file_path:
            continue
        source = Path(download.file_path).resolve()
        if not source.is_relative_to(root) or not source.is_file() or source.suffix.lower() not in _extensions:
            continue
        destination = destination_root / f"{item.id}-{1_000_000_000 + download.id}{source.suffix.lower()}"
        if not destination.is_file() or destination.stat().st_size != source.stat().st_size:
            with tempfile.NamedTemporaryFile(dir=destination_root, prefix=".legacy-", delete=False) as output:
                temporary = Path(output.name)
                try:
                    with source.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)
                    output.flush()
                    os.fsync(output.fileno())
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            os.replace(temporary, destination)
        artifact = session.scalar(select(Artifact).where(Artifact.path == str(destination)))
        if not artifact:
            reference = session.scalar(select(SourceReference).where(
                SourceReference.item_id == item.id, SourceReference.source_id == 'dailywire')
                .order_by(SourceReference.id.desc()))
            artifact = Artifact(item_id=item.id, profile_id=download.local_media_profile_id,
                source_reference_id=reference.id if reference else None,
                path=str(destination), size=destination.stat().st_size)
            session.add(artifact)
            session.flush()
        placement = session.scalar(select(ArtifactPlacement).where(
            ArtifactPlacement.path == str(source)))
        if not placement:
            session.add(ArtifactPlacement(artifact_id=artifact.id,
                profile_id=download.local_media_profile_id, path=str(source)))
        if not session.scalar(select(MediaDemand.id).where(MediaDemand.item_id == item.id,
            MediaDemand.profile_id == download.local_media_profile_id, MediaDemand.owner_kind == "direct")):
            session.add(MediaDemand(item_id=item.id, profile_id=download.local_media_profile_id,
                owner_kind="direct", owner_id=item.id))


def _migrate(context) -> None:
    with get_session() as session:
        count = int(session.scalar(select(func.count(Show.id))) or 0) + int(
            session.scalar(select(func.count(Movie.id))) or 0)
    if count == 0:
        return
    context.update_progress(0, count, "Importing the existing WireLoft library")
    processed = 0
    with get_session() as session:
        domain = _domain(session)
        session.commit()
        domain_id = domain.id

    with get_session() as session:
        for show in session.scalars(select(Show).order_by(Show.id)).all():
            context.raise_if_cancelled()
            domain = session.get(Domain, domain_id)
            collection = _item(session, domain, "show", show.id, "collection",
                show.slug, show.title, show.sharing_url, show.description,
                artwork=show.thumbnail_portrait_path or show.background_image_path)
            for position, episode in enumerate(show.episodes, 1):
                child = _item(session, domain, "episode", episode.id, "video",
                    episode.slug, episode.title, episode.sharing_url,
                    episode.description, episode.duration, episode.thumbnail_landscape_path)
                membership = session.scalar(select(CollectionEntry).where(
                    CollectionEntry.collection_id == collection.id, CollectionEntry.item_id == child.id))
                if not membership:
                    session.add(CollectionEntry(collection_id=collection.id, item_id=child.id,
                        position=position, group=episode.season.name if episode.season else None,
                        episode_number=episode.dw_episode_number))
                _copy_downloads(session, child, episode.downloads)
            session.commit()
            processed += 1
            context.update_progress(processed, count, "Imported Shows and Episodes")

        for movie in session.scalars(select(Movie).order_by(Movie.id)).all():
            context.raise_if_cancelled()
            domain = session.get(Domain, domain_id)
            parent = _item(session, domain, "videos", movie.id, "movie", movie.slug,
                movie.title, movie.sharing_url or f"https://www.dailywire.com/videos/{movie.slug}",
                movie.description, movie.duration, movie.thumbnail_portrait_path)
            _copy_downloads(session, parent, movie.downloads)
            for extra in movie.movie_extras:
                source = extra.source
                child = _item(session, domain, "clips", source.id, "movie_extra",
                    source.slug, source.title,
                    source.sharing_url or f"https://www.dailywire.com/clips/{source.slug}",
                    source.description, source.duration, source.thumbnail_landscape_path)
                child.parent_id = child.parent_id or parent.id
                child.extra_type = extra.movie_extra_type
                link = session.scalar(select(MovieExtraParent).where(
                    MovieExtraParent.movie_id == parent.id, MovieExtraParent.extra_id == child.id))
                if not link:
                    session.add(MovieExtraParent(movie_id=parent.id, extra_id=child.id,
                        extra_type=extra.movie_extra_type))
                _copy_downloads(session, child, extra.downloads)
            session.commit()
            processed += 1
            context.update_progress(processed, count, "Imported Movies and Extras")


async def migrate(context) -> None:
    await asyncio.to_thread(_migrate, context)
