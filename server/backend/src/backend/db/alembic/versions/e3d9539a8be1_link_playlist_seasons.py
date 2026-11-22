"""A channel collection's season of a playlist knows its playlist again.

TESTING ONLY: this fixes test databases that ran the old creators, which no release had (collection lists came after
0.9.1). Leave it out when the migrations are merged into the 0.10.0 release migration.

The old creators kept which season a creator's playlist filled on the creator's section, so a channel collection that
the simple creators migration (295b85b20467) left with those seasons has playlists that know no season of theirs. Such
a season is an ordinary season to VODLoft now: switching the playlist off never empties it, and no save removes it.

Each playlist without a season takes the season of its collection that has the playlist's name, when one season
does and no other playlist has it. A playlist whose season holds episodes is switched on, as its season is there, in a
collection whose playlists are on, so the user can switch it off in the Seasons window and its videos move.

Revision ID: e3d9539a8be1
Revises: 5133229960f5
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e3d9539a8be1"
down_revision = "5133229960f5"
branch_labels = None
depends_on = None

# Each playlist without a season, with the seasons of its channel collection named as it is that no playlist has.
_MATCHES = (
    "SELECT l.id, l.collection_id, s.id FROM collection_lists l "
    "JOIN collections c ON c.id = l.collection_id "
    "JOIN seasons s ON s.collection_id = l.collection_id AND s.name = l.title "
    "WHERE c.kind = 'channel' AND l.season_id IS NULL AND s.season_type != 'extra' AND s.loose = :off "
    "AND NOT EXISTS (SELECT 1 FROM collection_lists o WHERE o.season_id = s.id)"
)


def upgrade() -> None:
    bind = op.get_bind()
    matches = bind.execute(sa.text(_MATCHES), {"off": False}).all()
    seasons_of: dict[int, list[int]] = {}
    lists_of: dict[int, list[int]] = {}
    collection_of: dict[int, int] = {}
    for list_id, collection_id, season_id in matches:
        seasons_of.setdefault(list_id, []).append(season_id)
        lists_of.setdefault(season_id, []).append(list_id)
        collection_of[list_id] = collection_id
    # Only a name that picks one season, of one playlist, links them.
    linked = {
        list_id: seasons[0] for list_id, seasons in seasons_of.items()
        if len(seasons) == 1 and len(lists_of[seasons[0]]) == 1
    }
    if not linked:
        return
    for list_id, season_id in linked.items():
        bind.execute(sa.text("UPDATE collection_lists SET season_id = :season WHERE id = :id"), {"season": season_id, "id": list_id})
    filled = {
        list_id for list_id, season_id in linked.items()
        if bind.execute(sa.text("SELECT 1 FROM media_items_episode WHERE season_id = :season LIMIT 1"), {"season": season_id}).first()
    }
    if not filled:
        return
    bind.execute(
        sa.text("UPDATE collection_lists SET enabled = :on, status = 'known' WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)),
        {"ids": sorted(filled), "on": True},
    )
    bind.execute(
        sa.text("UPDATE collections SET link_seasons = 'selected' WHERE link_seasons = 'off' AND id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)),
        {"ids": sorted({collection_of[list_id] for list_id in filled})},
    )


def downgrade() -> None:
    # Which playlists took their season again is not kept.
    pass
