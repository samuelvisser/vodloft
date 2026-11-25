"""A collection with videos of its own no longer lays its lists out by year: its lists are included as contents only,
with the videos in none of them in a season per year, which puts every video in the same year seasons.

Revision ID: d571b0dc3805
Revises: 0421aa4848d2
Create Date: 2026-11-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d571b0dc3805"
down_revision = "0421aa4848d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    collections = sa.table(
        "collections", sa.column("id", sa.Integer), sa.column("list_layout", sa.String),
        sa.column("outside_videos", sa.String), sa.column("link_seasons", sa.String),
        sa.column("lists_as_seasons", sa.Boolean), sa.column("loose_videos", sa.String),
    )
    lists = sa.table("collection_lists", sa.column("collection_id", sa.Integer), sa.column("as_season", sa.Boolean))
    by_year = sa.and_(collections.c.list_layout == "by_year", collections.c.outside_videos != "only")
    lists_on = list(bind.execute(sa.select(collections.c.id).where(by_year, collections.c.link_seasons != "off")).scalars())
    if lists_on:
        bind.execute(collections.update().where(collections.c.id.in_(lists_on)).values(
            lists_as_seasons=False, loose_videos="by_year",
        ))
        bind.execute(lists.update().where(lists.c.collection_id.in_(lists_on)).values(as_season=False))
    bind.execute(collections.update().where(by_year).values(list_layout="season_each"))


def downgrade() -> None:
    # The year seasons stay as they are: contents-only lists with the other videos by year put them there too.
    pass
