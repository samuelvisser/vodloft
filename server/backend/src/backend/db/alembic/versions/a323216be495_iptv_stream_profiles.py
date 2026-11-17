"""Add IPTV stream profiles, and the stream tokens of the playlist and guide with every channel.

Revision ID: a323216be495
Revises: 555cdd9ad18a
Create Date: 2026-11-16

An IPTV stream profile is a TV channel, with its number and the group apps list it under. Each user,
and an install without user accounts, gets a secret token for one playlist and guide with all of their
channels. Existing rows get a token of their own here.
"""
from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op


revision = "a323216be495"
down_revision = "555cdd9ad18a"
branch_labels = None
depends_on = None


def _give_each_row_a_token(table: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id FROM {table}")).scalars().all()
    for row_id in rows:
        bind.execute(
            sa.text(f"UPDATE {table} SET stream_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(24), "id": row_id},
        )


def upgrade() -> None:
    op.create_table(
        "stream_profiles_iptv",
        sa.Column("id", sa.Integer(), sa.ForeignKey("stream_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_number", sa.Integer(), nullable=False, comment="Where the channel sits in an app's channel list"),
        sa.Column(
            "channel_group", sa.String(), nullable=True,
            comment="The group an app lists the channel under; empty uses the collection's Site name",
        ),
    )

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "stream_token", sa.String(), nullable=True,
            comment="Secret in the addresses of the user's own playlist and guide, with all their channels",
        ))
    _give_each_row_a_token("users")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("stream_token", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_users_stream_token", ["stream_token"])

    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column(
            "stream_token", sa.String(64), nullable=True,
            comment="Secret in the addresses of the playlist and guide with every channel, for an install without user accounts",
        ))
    _give_each_row_a_token("settings")
    with op.batch_alter_table("settings") as batch:
        batch.alter_column("stream_token", existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("stream_token")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_stream_token", type_="unique")
        batch.drop_column("stream_token")
    op.drop_table("stream_profiles_iptv")
