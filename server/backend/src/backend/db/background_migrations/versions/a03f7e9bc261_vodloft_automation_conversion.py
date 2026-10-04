"""Carry WireLoft automation into normalized Collections and scoped Source secrets.

Revision ID: a03f7e9bc261
Revises: 8e5a2c9f41d0
"""
import asyncio
import json
import uuid
from urllib.parse import urlsplit
from datetime import date, timedelta
from sqlalchemy import select
from backend.db import get_session
from backend.db.models import DownloadProfileBase, PodcastDownloadProfile, RssStreamProfile, Show
from backend.db.models.media_item import Episode, Movie, MovieExtraSource
from backend.db.models.vodloft import (Artifact, CollectionEntry, CollectionDownloadProfile, CollectionStreamProfile,
    FeedSubscription, LegacyMediaLink, MediaDemand, SourceConnection, SourceReference)
from backend.source_manager import secrets as secret_store
from backend.source_manager.runtime import command_for
from config import get_settings

revision = "a03f7e9bc261"
down_revision = "8e5a2c9f41d0"
title = "Convert existing media automation and accounts"


def _convert(context):
    # The old token store is read once. Future account authentication belongs
    # exclusively to the Source worker and encrypted generic connection store.
    try:
        from dailywire_authorisation.storage import TokenStore
        oauth = get_settings().dw_oauth
        credentials = TokenStore().load("|".join((oauth.issuer, oauth.client_id, oauth.audience, oauth.scope)))
    except Exception:
        credentials = None
    with get_session() as session:
        connection = session.scalar(select(SourceConnection).where(SourceConnection.name == "Imported WireLoft account"))
        if credentials and not connection:
            authentication = {"status": "authorized", "configuration": {"access_token": credentials.access_token},
                "expires_at": credentials.expires_at, "private_state": {"refresh_token": credentials.refresh_token},
                "_command": command_for("dailywire")[0]}
            reference = secret_store.save(json.dumps(authentication))
            connection = SourceConnection(source_id="dailywire", name="Imported WireLoft account",
                settings={}, secret_references={}, authentication_reference=reference, enabled=True)
            session.add(connection)
            session.flush()
            # Only legacy alias references belong to the imported account.
            # A previously imported public or other-account reference keeps
            # its original authorization scope, even for the same media.
            links = {(row.legacy_type, row.legacy_id): row.item_id
                for row in session.scalars(select(LegacyMediaLink)).all()}
            aliases = {(namespace, row.slug, links.get((namespace, row.id)))
                for namespace, model in [('show', Show), ('episode', Episode),
                    ('videos', Movie), ('clips', MovieExtraSource)]
                for row in session.scalars(select(model)).all()}
            for upstream in session.scalars(select(SourceReference).where(SourceReference.source_id == "dailywire",
                    SourceReference.connection_id.is_(None))).all():
                if (upstream.namespace, upstream.upstream_id, upstream.item_id) in aliases:
                    upstream.connection_id, upstream.connection_key = connection.id, connection.id
                    for entry in session.scalars(select(CollectionEntry).where(
                            CollectionEntry.collection_id == upstream.item_id,
                            CollectionEntry.source_id == "dailywire", CollectionEntry.connection_key == 0)).all():
                        entry.connection_id, entry.connection_key = connection.id, connection.id
        session.flush()
        groups = {}
        for upstream in session.scalars(select(SourceReference).where(SourceReference.source_id == "dailywire")).all():
            parts = urlsplit(upstream.url).path.strip("/").split("/")
            if len(parts) != 2:
                continue
            namespace = {"shows": "show", "episodes": "episode", "movies": "videos", "clip": "clips"}.get(parts[0], parts[0])
            canonical = f"https://www.dailywire.com/{namespace}/{parts[1]}"
            key = (upstream.domain_id, upstream.connection_key, namespace,
                str(uuid.uuid5(uuid.NAMESPACE_URL, canonical)), canonical)
            groups.setdefault(key, []).append(upstream)
        for (_, _, namespace, identity, canonical), references in groups.items():
            if len({reference.item_id for reference in references}) != 1:
                raise ValueError('Conflicting legacy canonical media identities require review')
            keep = next((reference for reference in references if
                reference.namespace == namespace and reference.upstream_id == identity), references[0])
            for duplicate in references:
                if duplicate.id == keep.id:
                    continue
                # Repoint every declared FK without changing frozen job specs
                # or playback lease bytes. The canonical media ID is retained.
                for table in SourceReference.metadata.sorted_tables:
                    for column in table.columns:
                        if any(foreign.column.table is SourceReference.__table__
                                for foreign in column.foreign_keys):
                            session.execute(table.update().where(column == duplicate.id)
                                .values({column.name: keep.id}))
                session.delete(duplicate)
            session.flush()
            keep.namespace, keep.upstream_id, keep.url = namespace, identity, canonical
            session.flush()
        links = {link.legacy_id: link.item_id for link in session.scalars(select(LegacyMediaLink).where(
            LegacyMediaLink.legacy_type == "show")).all()}
        for old in session.scalars(select(DownloadProfileBase)).all():
            context.raise_if_cancelled()
            if old.show_id not in links:
                continue
            name = f"Imported download profile {old.id}"
            if session.scalar(select(CollectionDownloadProfile.id).where(CollectionDownloadProfile.name == name)):
                continue
            collection_id = links[old.show_id]
            reference = session.scalar(select(SourceReference).where(SourceReference.item_id == collection_id,
                SourceReference.source_id == "dailywire",
                SourceReference.connection_key == (connection.id if connection else 0)))
            podcast = isinstance(old, PodcastDownloadProfile)
            count = old.download_episode_count if podcast else 0
            start = old.download_starting_from if podcast else None
            if podcast and old.download_days_in_past:
                start = max(start or date.min, date.today() - timedelta(days=old.download_days_in_past))
            session.add(CollectionDownloadProfile(collection_id=collection_id,
                source_reference_id=reference.id if reference else None, name=name,
                local_profile_ids=[old.local_media_profile_id], backfill="date_range" if start else "newest" if count else "all",
                newest_count=max(count, 1), published_after=start, enabled=old.enable_profile,
                refresh_minutes=60, retain_newest=count if podcast and old.delete_older_episodes and count else None,
                retain_days=old.download_days_in_past if podcast and old.delete_older_episodes and old.download_days_in_past else None))
        for old in session.scalars(select(RssStreamProfile)).all():
            if old.show_id not in links:
                continue
            name = f"Imported stream profile {old.id}"
            if session.scalar(select(CollectionStreamProfile.id).where(CollectionStreamProfile.name == name)):
                continue
            profile = CollectionStreamProfile(collection_id=links[old.show_id], name=name,
                format="audio" if old.preferred_format == "format_audio_only" else "video",
                local_only=not old.use_dw_stream, include_live=old.stream_live_episodes, enabled=old.enable_profile)
            session.add(profile)
            session.flush()
            session.add(FeedSubscription(collection_id=profile.collection_id, stream_profile_id=profile.id,
                user_key="admin", token=old.token))
        for artifact in session.scalars(select(Artifact).where(Artifact.profile_id.is_not(None))).all():
            if not session.scalar(select(MediaDemand.id).where(MediaDemand.item_id == artifact.item_id,
                    MediaDemand.profile_id == artifact.profile_id)):
                session.add(MediaDemand(item_id=artifact.item_id, profile_id=artifact.profile_id,
                    owner_kind="direct", owner_id=artifact.item_id))
        session.commit()


async def migrate(context):
    await asyncio.to_thread(_convert, context)
