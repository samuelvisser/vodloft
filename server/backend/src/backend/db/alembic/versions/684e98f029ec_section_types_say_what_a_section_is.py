"""A creator section's type says what it is; creators keep their new-list settings per Site

A Site's contract now names every type of section, its feeds too, and a section only keeps the key of its type:
``creator_sections.kind`` and ``role`` go, as the type says them, and a feed is named after its type, so it keeps no
title of its own. Feeds get the keys of their types, such as YouTube's videos, live and shorts.

Type keys are only unique within a Site, so ``creators.new_lists`` goes from ``{type: action}`` to
``{site: {type: action}}``: each of a creator's Sites gets the setting of each of its types the creator had.

Revision ID: 684e98f029ec
Revises: 7d3b9e41a6c2
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "684e98f029ec"
down_revision = "7d3b9e41a6c2"
branch_labels = None
depends_on = None

# The feed types of each Site when this migration was written, by the feed's ref; a feed of any other Site is its
# videos.
_FEEDS = {
    "youtube": {"videos": "videos", "streams": "live", "shorts": "shorts"},
    "soundcloud": {"tracks": "tracks"},
}
_OTHER_FEED = "videos"
# The types of list and show each Site's creators had, which have a new-list setting; any other Site has playlists.
_GROWING = {
    "youtube": ("list",),
    "soundcloud": ("album", "playlist"),
    "bandcamp": ("album",),
    "dailywire": ("show",),
}
_OTHER_GROWING = ("list",)
# For a downgrade: the kind and role of each type, and the title a feed had.
_KINDS = {"list": "list", "album": "list", "playlist": "list", "show": "show", "single": "item", "movie": "item"}
_ROLES = {"live": "live", "shorts": "short"}
_FEED_TITLES = {"videos": "Videos", "live": "Live", "shorts": "Shorts", "tracks": "Tracks"}


def _settings(value: str | dict | None) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def _site_keys(bind) -> dict[int, list[str]]:
    sites: dict[int, list[str]] = {}
    for creator_id, site_key in bind.execute(sa.text("SELECT creator_id, site_key FROM creator_accounts ORDER BY id")):
        if site_key not in sites.setdefault(creator_id, []):
            sites[creator_id].append(site_key)
    return sites


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT creator_sections.id, creator_accounts.site_key, creator_sections.ref"
        " FROM creator_sections JOIN creator_accounts ON creator_accounts.id = creator_sections.account_id"
        " WHERE creator_sections.kind = 'feed'"
    )).all()
    with op.batch_alter_table("creator_sections") as batch:
        batch.alter_column(
            "title", existing_type=sa.String(), nullable=True,
            comment="The title the Site gives a list, show or item; a feed is named after its type",
        )
        batch.alter_column(
            "type", existing_type=sa.String(), existing_nullable=False,
            comment="The key of the Site's section type it is, such as videos, list or album",
        )
    for section_id, site_key, ref in rows:
        bind.execute(sa.text("UPDATE creator_sections SET type = :type, title = NULL WHERE id = :id"),
                     {"type": _FEEDS.get(site_key, {}).get(ref, _OTHER_FEED), "id": section_id})
    with op.batch_alter_table("creator_sections") as batch:
        batch.drop_column("kind")
        batch.drop_column("role")

    sites = _site_keys(bind)
    for creator_id, value in bind.execute(sa.text("SELECT id, new_lists FROM creators")).all():
        settings = _settings(value)
        by_site = {
            site_key: {key: settings[key] for key in _GROWING.get(site_key, _OTHER_GROWING) if key in settings}
            for site_key in sites.get(creator_id, [])
        }
        by_site = {site_key: actions for site_key, actions in by_site.items() if actions}
        bind.execute(sa.text("UPDATE creators SET new_lists = :settings WHERE id = :id"),
                     {"settings": json.dumps(by_site), "id": creator_id})
    with op.batch_alter_table("creators") as batch:
        batch.alter_column(
            "new_lists", existing_type=sa.JSON(), existing_nullable=False, existing_server_default="{}",
            comment="What happens when the creator adds a list, by Site and type of list: ask, season, own or ignore",
        )


def downgrade() -> None:
    bind = op.get_bind()
    for creator_id, value in bind.execute(sa.text("SELECT id, new_lists FROM creators")).all():
        flat: dict[str, str] = {}
        for actions in _settings(value).values():
            for key, action in actions.items():
                flat.setdefault(key, action)
        bind.execute(sa.text("UPDATE creators SET new_lists = :settings WHERE id = :id"),
                     {"settings": json.dumps(flat), "id": creator_id})
    with op.batch_alter_table("creators") as batch:
        batch.alter_column(
            "new_lists", existing_type=sa.JSON(), existing_nullable=False, existing_server_default="{}",
            comment="What happens when the creator adds a list, by the kind of list: ask, season, own or ignore",
        )

    with op.batch_alter_table("creator_sections") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=True, comment="feed, list, show or item"))
        batch.add_column(sa.Column("role", sa.String(), nullable=False, server_default="main", comment="main, short or live"))
    for section_id, type_, title in bind.execute(sa.text("SELECT id, type, title FROM creator_sections")).all():
        kind = _KINDS.get(type_, "feed")
        bind.execute(sa.text(
            "UPDATE creator_sections SET kind = :kind, role = :role, type = :type, title = :title WHERE id = :id"
        ), {
            "kind": kind, "role": _ROLES.get(type_, "main"), "type": "feed" if kind == "feed" else type_,
            "title": title if title is not None else _FEED_TITLES.get(type_, "Videos"), "id": section_id,
        })
    with op.batch_alter_table("creator_sections") as batch:
        batch.alter_column("kind", existing_type=sa.String(), nullable=False)
        batch.alter_column("title", existing_type=sa.String(), nullable=False, comment=None)
        batch.alter_column(
            "type", existing_type=sa.String(), existing_nullable=False,
            comment="The key of the Site's section type it is, such as feed, list or album",
        )
