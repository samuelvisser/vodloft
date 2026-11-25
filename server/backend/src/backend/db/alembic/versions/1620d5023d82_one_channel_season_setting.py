"""How a channel collection groups its own videos is one setting.

What the channel season held (``channel_season``: everything or unlisted) and where the videos in no playlist went
(``loose_videos``: one_season or by_year) were two settings of one choice. They are one now, ``loose_videos``:
everything, one season with every video of the channel; one_season, one season of what is in no playlist; or by_year.
A channel collection whose playlists are not seasons put its videos in a season per year, so it keeps that.

Revision ID: 1620d5023d82
Revises: b7e4c1a9d052
Create Date: 2026-11-25
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "1620d5023d82"
down_revision = "b7e4c1a9d052"
branch_labels = None
depends_on = None

_collections = sa.table(
    "collections",
    sa.column("id", sa.Integer), sa.column("kind", sa.String), sa.column("link_seasons", sa.String),
    sa.column("loose_videos", sa.String), sa.column("channel_season", sa.String), sa.column("move_causes", sa.JSON),
)


def _grouping(link_seasons: str | None, loose_videos: str | None, channel_season: str | None) -> str | None:
    """A channel collection's one setting, from the two settings it had."""
    if link_seasons == "off" or loose_videos == "by_year":
        return "by_year"
    return "everything" if channel_season == "everything" else "one_season"


def _cause(causes: list[dict], setting: str) -> dict | None:
    return next((cause for cause in causes if cause.get("setting") == setting and cause.get("origin") == "seasons"), None)


def _causes(row, grouping: str | None) -> list[dict] | None:
    """The changes waiting for the Move action, with the two settings' changes as one change of the setting."""
    causes = row.move_causes
    if isinstance(causes, str):
        causes = json.loads(causes)
    if not causes:
        return None
    loose, channel, link = (_cause(causes, name) for name in ("loose_videos", "channel_season", "link_seasons"))
    if loose is None and channel is None:
        return None
    before = _grouping(
        link["before"] if link is not None else row.link_seasons,
        loose["before"] if loose is not None else row.loose_videos,
        channel["before"] if channel is not None else row.channel_season,
    )
    kept = [cause for cause in causes if cause not in (loose, channel)]
    if before != grouping:
        kept.append({**(loose or channel), "setting": "loose_videos", "before": before, "after": grouping})
    return kept


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(
        _collections.c.id, _collections.c.link_seasons, _collections.c.loose_videos, _collections.c.channel_season,
        _collections.c.move_causes,
    ).where(_collections.c.kind == "channel")).all()
    for row in rows:
        grouping = _grouping(row.link_seasons, row.loose_videos, row.channel_season)
        values: dict = {"loose_videos": grouping}
        causes = _causes(row, grouping)
        if causes is not None:
            values["move_causes"] = causes
        bind.execute(_collections.update().where(_collections.c.id == row.id).values(**values))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("channel_season")
    else:
        op.drop_column("collections", "channel_season")


def downgrade() -> None:
    op.add_column("collections", sa.Column(
        "channel_season", sa.String(), nullable=False, server_default="unlisted",
        comment="What the channel season holds: everything, every video of the feeds, or unlisted, those in no list",
    ))
    bind = op.get_bind()
    bind.execute(_collections.update().where(_collections.c.loose_videos == "everything").values(
        channel_season="everything", loose_videos="one_season",
    ))
