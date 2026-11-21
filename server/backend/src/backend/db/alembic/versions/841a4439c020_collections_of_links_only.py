"""Collections that hold only what their link seasons have.

A collection can hold only the videos of its link seasons. Such a collection needs no link of its own, and its link
seasons can be links the user added, from any Site its Source fetches.

Revision ID: 841a4439c020
Revises: 3564f2e6fe1c
Create Date: 2026-11-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "841a4439c020"
down_revision = "3564f2e6fe1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("sharing_url", existing_type=sa.String(), nullable=True)
        batch.alter_column(
            "outside_videos", existing_type=sa.String(), existing_nullable=False, existing_server_default="leave_out",
            comment=(
                "What happens with the videos of the playlists that are seasons that the collection's own link does "
                "not list: leave_out, add, or only, which holds nothing but the videos of those playlists"
            ),
        )
    with op.batch_alter_table("link_seasons") as batch:
        batch.add_column(sa.Column(
            "added_by_user", sa.Boolean(), nullable=False, server_default="0",
            comment="The user added the link, rather than it being one of the playlists of the collection's channel",
        ))


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("link_seasons") as batch:
        batch.drop_column("added_by_user")
    # A collection that only held its link seasons' videos goes back to adding them beside its own; one without a
    # link of its own can't be kept.
    bind.execute(sa.text("UPDATE collections SET outside_videos = 'add' WHERE outside_videos = 'only'"))
    bind.execute(sa.text("DELETE FROM collections WHERE sharing_url IS NULL"))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column(
            "outside_videos", existing_type=sa.String(), existing_nullable=False, existing_server_default="leave_out",
            comment="What happens with the videos of the playlists that are seasons that the collection's own link does not list: leave_out or add",
        )
        batch.alter_column("sharing_url", existing_type=sa.String(), nullable=False)
