"""What happens with a creator's new list is set for each kind of list

A Site can tell more than one kind of list apart, such as a SoundCloud artist's albums and their playlists, and each
kind has a setting of its own. ``creators.new_sections`` and ``collections.new_link_seasons`` become ``new_lists``,
which keep the setting by the kind's key: every kind of the Sites starts with the setting it had.

Revision ID: 9c3e1f5a7b20
Revises: 5e0c7a2b91d4
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "9c3e1f5a7b20"
down_revision = "5e0c7a2b91d4"
branch_labels = None
depends_on = None

# The kinds of list each Site had when this migration was written; any other Site has one, "list".
_KINDS = {"soundcloud": ("album", "playlist")}


def _kinds(site_keys: set[str | None]) -> list[str]:
    kinds = [kind for key in sorted(key or "" for key in site_keys) for kind in _KINDS.get(key, ("list",))]
    return list(dict.fromkeys(kinds or ["list"]))


def upgrade() -> None:
    with op.batch_alter_table("creators") as batch:
        batch.add_column(sa.Column(
            "new_lists", sa.JSON(), nullable=False, server_default="{}",
            comment="What happens when the creator adds a list, by the kind of list: ask, season, own or ignore",
        ))
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "new_lists", sa.JSON(), nullable=False, server_default="{}",
            comment=(
                "What happens with a list the creator adds, by the kind of list, when only selected lists are seasons: "
                "ask, add or ignore"
            ),
        ))
    bind = op.get_bind()
    sites: dict[int, set[str | None]] = {}
    for creator_id, site_key in bind.execute(sa.text("SELECT creator_id, site_key FROM creator_accounts")):
        sites.setdefault(creator_id, set()).add(site_key)
    for creator_id, action in bind.execute(sa.text("SELECT id, new_sections FROM creators")).all():
        settings = {kind: action for kind in _kinds(sites.get(creator_id, set()))}
        bind.execute(sa.text("UPDATE creators SET new_lists = :settings WHERE id = :id"),
                     {"settings": json.dumps(settings), "id": creator_id})
    for collection_id, site_key, action in bind.execute(
        sa.text("SELECT id, site_key, new_link_seasons FROM collections")
    ).all():
        settings = {kind: action for kind in _kinds({site_key})}
        bind.execute(sa.text("UPDATE collections SET new_lists = :settings WHERE id = :id"),
                     {"settings": json.dumps(settings), "id": collection_id})
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("new_sections")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("new_link_seasons")


def _first(settings: str | dict | None, default: str) -> str:
    if isinstance(settings, str):
        settings = json.loads(settings)
    return next(iter((settings or {}).values()), default)


def downgrade() -> None:
    with op.batch_alter_table("creators") as batch:
        batch.add_column(sa.Column("new_sections", sa.String(), nullable=False, server_default="ask"))
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("new_link_seasons", sa.String(), nullable=False, server_default="ask"))
    bind = op.get_bind()
    for creator_id, settings in bind.execute(sa.text("SELECT id, new_lists FROM creators")).all():
        bind.execute(sa.text("UPDATE creators SET new_sections = :action WHERE id = :id"),
                     {"action": _first(settings, "ask"), "id": creator_id})
    for collection_id, settings in bind.execute(sa.text("SELECT id, new_lists FROM collections")).all():
        bind.execute(sa.text("UPDATE collections SET new_link_seasons = :action WHERE id = :id"),
                     {"action": _first(settings, "ask"), "id": collection_id})
    with op.batch_alter_table("creators") as batch:
        batch.drop_column("new_lists")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("new_lists")
