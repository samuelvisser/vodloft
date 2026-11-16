"""Add what an IPTV channel shows between live episodes, its catch-up window and its episode playlist.

Revision ID: affb021acdf2
Revises: a323216be495
Create Date: 2026-11-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "affb021acdf2"
down_revision = "a323216be495"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        batch.add_column(sa.Column(
            "between_live_episodes", sa.String(32), nullable=False, server_default="newest_episode",
            comment="What the channel shows while none of its episodes is live: an IptvBetweenLiveEpisodes value",
        ))
        batch.add_column(sa.Column(
            "catch_up_days", sa.Integer(), nullable=False, server_default="7",
            comment="How many days back the guide reaches, and apps can play an episode again from it",
        ))
        batch.add_column(sa.Column(
            "list_episodes", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Whether the channel's episodes are also listed on their own, in the episode playlist",
        ))
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        for column in ("between_live_episodes", "catch_up_days", "list_episodes"):
            batch.alter_column(column, server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        batch.drop_column("list_episodes")
        batch.drop_column("catch_up_days")
        batch.drop_column("between_live_episodes")
