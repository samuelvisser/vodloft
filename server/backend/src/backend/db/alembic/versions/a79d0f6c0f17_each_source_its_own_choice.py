"""Each of a collection's sources has a choice of its own: every list is a season of its own, part of the collection,
or off, and so is every feed of its channel.

Lists were in by one of two settings: every list (``link_seasons`` all, with ``lists_as_seasons`` saying whether each
was a season or contents only) or the ones the user picked (selected). Now a collection's lists are simply on or off
(``link_seasons`` on), and each list says what it is. A collection that had every list in has each of them on as it
was included, and takes new ones the same way.

A collection of nothing but its lists that laid them out by year (``list_layout`` by_year) includes its lists as part of
the collection, with what is part of it in a season per year, as a collection with videos of its own does already.

A feed of a channel collection can be a season of its own: ``feed_seasons`` holds the feeds that are, with their
season. A list remembers its type, such as an album or a playlist on SoundCloud, once VODLoft lists it again.

Revision ID: a79d0f6c0f17
Revises: d571b0dc3805
Create Date: 2026-11-25
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "a79d0f6c0f17"
down_revision = "d571b0dc3805"
branch_labels = None
depends_on = None

_collections = sa.table(
    "collections",
    sa.column("id", sa.Integer), sa.column("link_seasons", sa.String), sa.column("lists_as_seasons", sa.Boolean),
    sa.column("list_layout", sa.String), sa.column("outside_videos", sa.String), sa.column("loose_videos", sa.String),
    sa.column("new_lists", sa.JSON), sa.column("move_causes", sa.JSON),
)
_lists = sa.table(
    "collection_lists",
    sa.column("collection_id", sa.Integer), sa.column("enabled", sa.Boolean), sa.column("status", sa.String),
    sa.column("as_season", sa.Boolean), sa.column("added_by_user", sa.Boolean),
)
# Settings that are gone, and the values of the one that changed, in the changes that wait for the Move action.
_GONE = frozenset({"lists_as_seasons", "list_layout"})
_LINK_SEASONS = {"all": "on", "selected": "on"}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _causes(causes) -> list[dict] | None:
    causes = _json(causes)
    if not causes:
        return None
    kept = []
    for cause in causes:
        if cause.get("setting") in _GONE:
            continue
        if cause.get("setting") == "link_seasons":
            cause = {**cause, "before": _LINK_SEASONS.get(cause.get("before"), cause.get("before")),
                     "after": _LINK_SEASONS.get(cause.get("after"), cause.get("after"))}
            if cause["before"] == cause["after"]:
                continue
        kept.append(cause)
    return kept


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(
        _collections.c.id, _collections.c.link_seasons, _collections.c.lists_as_seasons, _collections.c.list_layout,
        _collections.c.outside_videos, _collections.c.new_lists, _collections.c.move_causes,
    )).all()
    for row in rows:
        values: dict = {}
        only = row.outside_videos == "only"
        if row.link_seasons == "all":
            # Every list was in, each as the collection said; new ones came in the same way.
            as_season = True if only else bool(row.lists_as_seasons)
            bind.execute(_lists.update().where(
                _lists.c.collection_id == row.id, _lists.c.added_by_user.is_(False),
            ).values(enabled=True, status="known", as_season=as_season))
            action = "add" if as_season else "contents"
            values["new_lists"] = {key: action for key in (_json(row.new_lists) or {})}
        if only and row.list_layout == "by_year" and row.link_seasons != "off":
            # The lists decide what is in; what is part of the collection goes in a season per year.
            bind.execute(_lists.update().where(_lists.c.collection_id == row.id).values(as_season=False))
            values["loose_videos"] = "by_year"
        if row.link_seasons in _LINK_SEASONS:
            values["link_seasons"] = _LINK_SEASONS[row.link_seasons]
        causes = _causes(row.move_causes)
        if causes is not None:
            values["move_causes"] = causes
        if values:
            bind.execute(_collections.update().where(_collections.c.id == row.id).values(**values))
    column = sa.Column(
        "feed_seasons", sa.JSON(), nullable=False, server_default="{}",
        comment="The feeds of the channel that are a season of their own, by ref, with their season's id once it has "
                "one, which lists or other feeds may share",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("lists_as_seasons")
            batch.drop_column("list_layout")
            batch.add_column(column)
    else:
        op.drop_column("collections", "lists_as_seasons")
        op.drop_column("collections", "list_layout")
        op.add_column("collections", column)
    op.add_column("collection_lists", sa.Column(
        "type_key", sa.String(), nullable=True,
        comment="The key of the list's type on its Site, such as album or playlist, once VODLoft listed it",
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("collections") as batch:
            batch.drop_column("feed_seasons")
        with op.batch_alter_table("collection_lists") as batch:
            batch.drop_column("type_key")
    else:
        op.drop_column("collections", "feed_seasons")
        op.drop_column("collection_lists", "type_key")
    op.add_column("collections", sa.Column("lists_as_seasons", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("collections", sa.Column("list_layout", sa.String(), nullable=False, server_default="season_each"))
    bind.execute(_collections.update().where(_collections.c.link_seasons == "on").values(link_seasons="selected"))
