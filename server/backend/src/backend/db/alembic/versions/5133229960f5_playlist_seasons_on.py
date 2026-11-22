"""A collection that still has seasons of its lists takes its lists again.

Under the old creators, a creator placed its lists in its collections whatever the collection's own playlist setting
said, so a channel collection can hold seasons of its lists while that setting is off. Now only the setting decides,
and with it off the Seasons window offers no way to switch those lists off, so their seasons stay for good.

Each such collection takes the lists that have a season with episodes, and only those: its setting becomes
"selected", those lists are switched on, and its other lists stay as they were. The user can then switch any of them
off in the Seasons window.

Revision ID: 5133229960f5
Revises: e2734b184864
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "5133229960f5"
down_revision = "e2734b184864"
branch_labels = None
depends_on = None

# The lists whose season holds episodes, in the channel collections whose playlist setting is off.
_STUCK_LISTS = (
    "SELECT l.id, l.collection_id FROM collection_lists l JOIN collections c ON c.id = l.collection_id "
    "WHERE c.link_seasons = 'off' AND c.kind = 'channel' AND l.season_id IS NOT NULL "
    "AND EXISTS (SELECT 1 FROM media_items_episode e WHERE e.season_id = l.season_id)"
)


def upgrade() -> None:
    bind = op.get_bind()
    stuck = bind.execute(sa.text(_STUCK_LISTS)).all()
    list_ids = [list_id for list_id, _collection_id in stuck]
    collection_ids = sorted({collection_id for _list_id, collection_id in stuck})
    if not list_ids:
        return
    bind.execute(
        sa.text("UPDATE collections SET link_seasons = 'selected' WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)),
        {"ids": collection_ids},
    )
    bind.execute(
        sa.text("UPDATE collection_lists SET enabled = :on, status = 'known' WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True)),
        {"ids": list_ids, "on": True},
    )


def downgrade() -> None:
    # Which collections had their lists switched back on is not kept.
    pass
