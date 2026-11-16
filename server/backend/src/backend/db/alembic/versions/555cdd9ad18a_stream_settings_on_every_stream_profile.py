"""Move the settings every stream profile type shares from the RSS table to stream_profiles.

Revision ID: 555cdd9ad18a
Revises: bb0e7c5e17cc
Create Date: 2026-11-16

How many episodes a profile offers, whether it streams live episodes and passes its Site's stream on
through VODLoft, and the live episodes it keeps playing from the Site until their download lands
apply to every stream profile type, not only to RSS feeds. Each feed keeps its values.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "555cdd9ad18a"
down_revision = "bb0e7c5e17cc"
branch_labels = None
depends_on = None

_SHARED = ("max_items", "stream_live_episodes", "proxy_source_stream", "live_episode_handoff_ids")


def _columns() -> list[sa.Column]:
    return [
        sa.Column(
            "max_items", sa.Integer(), nullable=False, server_default="0",
            comment="The most episodes offered, newest first; 0 offers every one",
        ),
        sa.Column("stream_live_episodes", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "proxy_source_stream", sa.Boolean(), nullable=False, server_default="1",
            comment="Pass the Site's stream on through VODLoft instead of sending apps to the Site",
        ),
        sa.Column("live_episode_handoff_ids", sa.JSON(), nullable=False, server_default="[]"),
    ]


def _copy(source: str, target: str) -> None:
    """Copy the shared values of every RSS feed from one table to the other, by its id."""
    assignments = ", ".join(
        f"{column} = (SELECT {source}.{column} FROM {source} WHERE {source}.id = {target}.id)"
        for column in _SHARED
    )
    op.execute(sa.text(f"UPDATE {target} SET {assignments} WHERE id IN (SELECT id FROM {source})"))


def upgrade() -> None:
    with op.batch_alter_table("stream_profiles") as batch:
        for column in _columns():
            batch.add_column(column)
    _copy("stream_profiles_rss", "stream_profiles")
    with op.batch_alter_table("stream_profiles_rss") as batch:
        for column in _SHARED:
            batch.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        for column in _columns():
            batch.add_column(column)
    _copy("stream_profiles", "stream_profiles_rss")
    with op.batch_alter_table("stream_profiles") as batch:
        for column in _SHARED:
            batch.drop_column(column)
