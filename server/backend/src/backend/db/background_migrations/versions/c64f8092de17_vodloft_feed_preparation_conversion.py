"""Retain legacy feed account, quality, and live admission choices.

Revision ID: c64f8092de17
Revises: 0b87c419ad62
"""
import asyncio
from pathlib import Path
from sqlalchemy import select

from backend.db import get_session
from backend.db.models import RssStreamProfile, Episode
from backend.db.models.local_media_profile import DomainLocalMediaProfile
from backend.db.models.vodloft import (Artifact, CollectionStreamProfile, LegacyMediaLink,
    LiveAdmission, MediaItem, SourceConnection, SourceReference)
from source_contracts import RepresentationPolicy

revision = 'c64f8092de17'
down_revision = '0b87c419ad62'
title = 'Convert feed preparation and live archive admission'


def _convert(context):
    with get_session() as session:
        links = {(row.legacy_type, row.legacy_id): row.item_id
            for row in session.scalars(select(LegacyMediaLink)).all()}
        connection = session.scalar(select(SourceConnection).where(
            SourceConnection.source_id == 'dailywire', SourceConnection.name == 'Imported WireLoft account'))
        for old in session.scalars(select(RssStreamProfile)).all():
            context.raise_if_cancelled()
            profile = session.scalar(select(CollectionStreamProfile).where(
                CollectionStreamProfile.name == f'Imported stream profile {old.id}'))
            if not profile:
                continue
            collection = session.get(MediaItem, profile.collection_id)
            reference = session.scalar(select(SourceReference).where(
                SourceReference.item_id == collection.id, SourceReference.source_id == 'dailywire',
                SourceReference.connection_key == (connection.id if connection else 0)))
            profile.source_reference_id = reference.id if reference else None
            profile.allow_other_renditions = not old.prefer_exact_match
            if old.use_dw_stream:
                slug = f'vodloft-imported-feed-{old.id}'
                local = session.scalar(select(DomainLocalMediaProfile).where(DomainLocalMediaProfile.slug == slug))
                if not local:
                    audio = old.preferred_format == 'format_audio_only'
                    local = DomainLocalMediaProfile(slug=slug, name=f'Imported feed media {old.id}',
                        domain_id=collection.domain_id, applicable_kinds=['video'],
                        preferred_format=old.preferred_format, enabled=True,
                        output_template='/downloads/{{ domain }}/feeds/{{ collection }}/{{ title }} - {{ id }}.ext',
                        representation=RepresentationPolicy(container='mp3' if audio else 'mp4').model_dump())
                    session.add(local); session.flush()
                profile.local_profile_ids = [local.id]
            elif old.prefer_exact_match:
                profile.local_profile_ids = list(session.scalars(select(DomainLocalMediaProfile.id).where(
                    DomainLocalMediaProfile.domain_id == collection.domain_id,
                    DomainLocalMediaProfile.preferred_format == old.preferred_format)).all())
            for episode_id in old.live_episode_handoff_ids:
                item_id = links.get(('episode', episode_id))
                if not item_id or not reference or session.scalar(select(LiveAdmission.id).where(
                        LiveAdmission.stream_profile_id == profile.id, LiveAdmission.item_id == item_id)):
                    continue
                upstream = session.scalar(select(SourceReference).where(
                    SourceReference.item_id == item_id, SourceReference.source_id == reference.source_id,
                    SourceReference.connection_key == reference.connection_key))
                if not upstream:
                    continue
                portable = {'.mp3', '.m4a'} if profile.format == 'audio' else {'.mp4'}
                local = any(Path(artifact.path).is_file() and Path(artifact.path).suffix.lower() in portable
                    for artifact in session.scalars(select(Artifact).where(Artifact.item_id == item_id)).all())
                session.add(LiveAdmission(stream_profile_id=profile.id, item_id=item_id,
                    source_reference_id=upstream.id, state='local' if local else 'waiting'))
        for old in session.scalars(select(Episode)).all():
            item_id = links.get(('episode', old.id))
            if item_id and session.get(MediaItem, item_id).is_live is None:
                session.get(MediaItem, item_id).is_live = old.publish_status.casefold() == 'live'
        session.commit()


async def migrate(context):
    await asyncio.to_thread(_convert, context)
