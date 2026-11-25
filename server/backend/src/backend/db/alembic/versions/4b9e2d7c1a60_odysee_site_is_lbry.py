"""Odysee's Site key is lbry, the yt-dlp extractor module its links go to.

Odysee's contract went by the key odysee, while every Odysee link a Site was made from got the key lbry, the yt-dlp
module that reads them. Only a Site added by Odysee's home page got the key odysee. Its collections, videos, creators,
lists and Local Media Profile choices move to the lbry Site, which takes the odysee Site's place.

Revision ID: 4b9e2d7c1a60
Revises: 1620d5023d82
Create Date: 2026-11-25
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "4b9e2d7c1a60"
down_revision = "1620d5023d82"
branch_labels = None
depends_on = None

_OLD, _NEW = "odysee", "lbry"
_REFERRING = ("collections", "media_items_video", "creator_accounts", "collection_lists")

_sites = sa.table(
    "sites", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("domains", sa.JSON),
    sa.column("preferred_source_key", sa.String), sa.column("position", sa.Integer),
    sa.column("downloads_paused_until", sa.DateTime),
)
_profiles = sa.table("local_media_profiles", sa.column("id", sa.Integer), sa.column("site_keys", sa.JSON))


def _listed(value) -> list:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value or [])


def upgrade() -> None:
    bind = op.get_bind()
    old = bind.execute(sa.select(_sites).where(_sites.c.key == _OLD)).mappings().first()
    if old is None:
        return
    new = bind.execute(sa.select(_sites).where(_sites.c.key == _NEW)).mappings().first()
    if new is None:
        bind.execute(_sites.insert().values({**old, "key": _NEW, "name": "Odysee"}))
    else:
        domains = _listed(new["domains"]) + [d for d in _listed(old["domains"]) if d not in _listed(new["domains"])]
        bind.execute(_sites.update().where(_sites.c.key == _NEW).values(name="Odysee", domains=domains))
    for table in _REFERRING:
        referring = sa.table(table, sa.column("site_key", sa.String))
        bind.execute(referring.update().where(referring.c.site_key == _OLD).values(site_key=_NEW))
    for profile in bind.execute(sa.select(_profiles.c.id, _profiles.c.site_keys)).all():
        keys = _listed(profile.site_keys)
        if _OLD in keys:
            moved = [key for key in dict.fromkeys(_NEW if key == _OLD else key for key in keys)]
            bind.execute(_profiles.update().where(_profiles.c.id == profile.id).values(site_keys=moved))
    bind.execute(_sites.delete().where(_sites.c.key == _OLD))


def downgrade() -> None:
    # The two Sites became one; which of their records were the odysee Site's is no longer known.
    pass
