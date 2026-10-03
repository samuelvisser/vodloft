"""Preserve existing group selections, roles and RSS publication choices.

Revision ID: 0b87c419ad62
Revises: a03f7e9bc261
"""
import asyncio
from sqlalchemy import select
from backend.db import get_session
from backend.db.models import DownloadProfileBase, SeriesDownloadProfile, RssStreamProfile, Episode
from backend.db.models.vodloft import (CollectionEntry, CollectionDownloadProfile,
    CollectionStreamProfile, LegacyMediaLink, MediaItem)
from backend.services.vodloft_collections import known_groups

revision = '0b87c419ad62'
down_revision = 'a03f7e9bc261'
title = 'Preserve imported membership and feed policies'
_roles = {'ep': 'episode', 'ep-extra': 'episode_extra', 'trailer': 'trailer', 'aux': 'auxiliary'}


def _convert(context):
    with get_session() as session:
        links = {(row.legacy_type, row.legacy_id): row.item_id
            for row in session.scalars(select(LegacyMediaLink)).all()}
        for episode in session.scalars(select(Episode)).all():
            context.raise_if_cancelled()
            item_id, collection_id = links.get(('episode', episode.id)), links.get(('show', episode.show_id))
            if not item_id or not collection_id:
                continue
            entry = session.scalar(select(CollectionEntry).where(CollectionEntry.item_id == item_id,
                CollectionEntry.collection_id == collection_id))
            if entry:
                entry.role = _roles.get(episode.episode_type)
            item = session.get(MediaItem, item_id)
            item.published_at = episode.published_date
            item.normalized_metadata = {**(item.normalized_metadata or {}), 'author': episode.show.author_name}
        for old in session.scalars(select(DownloadProfileBase)).all():
            profile = session.scalar(select(CollectionDownloadProfile).where(
                CollectionDownloadProfile.name == f'Imported download profile {old.id}'))
            if not profile:
                continue
            profile.member_roles = [_roles[role] for role in old.ep_id_type_list if role in _roles]
            if isinstance(old, SeriesDownloadProfile):
                profile.selected_groups = list(dict.fromkeys(season.name for season in old.seasons))
                profile.include_future_groups = old.include_upcoming_seasons
                profile.known_groups = list(dict.fromkeys(season.name for season in old.show.seasons))
        for old in session.scalars(select(RssStreamProfile)).all():
            profile = session.scalar(select(CollectionStreamProfile).where(
                CollectionStreamProfile.name == f'Imported stream profile {old.id}'))
            if profile:
                profile.member_roles = [_roles[role] for role in old.ep_id_type_list if role in _roles]
                profile.max_items = old.max_items
                profile.feed_title = old.overwrite_show_title
                profile.known_groups = known_groups(session, profile.collection_id)
        session.commit()


async def migrate(context):
    await asyncio.to_thread(_convert, context)
