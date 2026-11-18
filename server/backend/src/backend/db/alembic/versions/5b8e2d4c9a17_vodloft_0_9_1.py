"""Upgrade the VODLoft 0.9.0 schema to 0.9.1.

Revision ID: 5b8e2d4c9a17
Revises: 2f7a91c4d8e3
Create Date: 2026-11-18

The single release migration for 0.9.1. It runs the steps of the migrations it replaces in their
order; each step's docstring says what it does.

A WebDAV stream profile's title becomes its folder name, WebDAV shares only list downloads and can list
an episode's extras beside it, and every collection numbers its extras with VODLoft's own extra index.
"""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op


revision = "5b8e2d4c9a17"
down_revision = "2f7a91c4d8e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _upgrade_webdav_title_is_folder_name()
    _upgrade_webdav_shares_only_list_downloads()
    _upgrade_webdav_episode_extras()
    _upgrade_episode_extra_index()


def downgrade() -> None:
    _downgrade_episode_extra_index()
    _downgrade_webdav_episode_extras()
    _downgrade_webdav_shares_only_list_downloads()
    _downgrade_webdav_title_is_folder_name()


def _upgrade_webdav_title_is_folder_name() -> None:
    """WebDAV stream profiles had a folder name beside their title, which only stood in for the title when it
    was empty. The title now names the show's folder, so a folder name that was set becomes the title, and
    the column goes."""
    # A title that is the collection's own is stored as nothing, as the API stores it.
    op.execute(sa.text(
        "UPDATE stream_profiles SET overwrite_collection_title = ("
        " SELECT CASE WHEN w.folder_name = c.title THEN NULL ELSE w.folder_name END"
        " FROM stream_profiles_webdav w JOIN collections c ON c.id = stream_profiles.collection_id"
        " WHERE w.id = stream_profiles.id"
        ") WHERE id IN (SELECT id FROM stream_profiles_webdav WHERE folder_name IS NOT NULL)"
    ))
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.drop_column("folder_name")


def _downgrade_webdav_title_is_folder_name() -> None:
    # An empty folder name used the title, so every share keeps its folder.
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.add_column(sa.Column(
            "folder_name", sa.String(), nullable=True, comment="The show's folder; empty uses the profile's title",
        ))


def _upgrade_webdav_shares_only_list_downloads() -> None:
    """A WebDAV share no longer streams episodes straight from their Site, so every WebDAV stream profile now
    uses downloads and never the Site's stream."""
    stream_profiles = sa.table(
        "stream_profiles",
        sa.column("type", sa.String),
        sa.column("use_downloads", sa.Boolean),
        sa.column("use_source_stream", sa.Boolean),
    )
    op.execute(
        stream_profiles.update()
        .where(stream_profiles.c.type == "webdav")
        .values(use_downloads=True, use_source_stream=False)
    )


def _downgrade_webdav_shares_only_list_downloads() -> None:
    # Which shares streamed from their Site before is not kept; they stay downloads only.
    pass


def _upgrade_webdav_episode_extras() -> None:
    """WebDAV shares can list the extras of an episode beside it. Existing shares keep listing them in the
    show's Trailers and Other folders."""
    op.add_column(
        "stream_profiles_webdav",
        sa.Column(
            "episode_extras", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="List the extras of an episode beside it, named after its file; otherwise in the show's Trailers and Other folders",
        ),
    )


def _downgrade_webdav_episode_extras() -> None:
    with op.batch_alter_table("stream_profiles_webdav") as batch:
        batch.drop_column("episode_extras")


def _upgrade_episode_extra_index() -> None:
    """An extra is an episode of an Extras season or of a type other than ep. A collection's extras are
    numbered together, in the order of their episode index."""
    op.add_column(
        "media_items_episode",
        sa.Column(
            "extra_index", sa.Integer(), nullable=True,
            comment="VODLoft's number for an extra: an episode of an Extras season or of a type other than ep. "
                    "Extras are numbered in the order of their index, and an extra keeps its number",
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT e.id, e.collection_id, e.episode_identifier, s.season_type FROM media_items_episode e "
        "JOIN seasons s ON s.id = e.season_id ORDER BY e.collection_id, e.\"index\", e.id"
    )).all()
    counts: dict[int, int] = defaultdict(int)
    numbers = []
    for episode_id, collection_id, identifier, season_type in rows:
        if season_type == "extra" or (identifier or "").partition(".")[0] != "ep":
            counts[collection_id] += 1
            numbers.append({"id": episode_id, "number": counts[collection_id]})
    if numbers:
        bind.execute(sa.text("UPDATE media_items_episode SET extra_index = :number WHERE id = :id"), numbers)


def _downgrade_episode_extra_index() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("extra_index")
