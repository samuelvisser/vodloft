"""A creator's own collection lists only the feeds placed in it

A creator's own collection keeps which of the creator's feeds its link lists. One that holds only what its playlists
give it lists none, and an artist's such collection now includes media that is not in the collection: its own link
lists nothing, so only its albums' tracks come in, and a feed placed in it later shows up.

Revision ID: 5e0c7a2b91d4
Revises: bd6c56bd1a8d
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5e0c7a2b91d4"
down_revision = "bd6c56bd1a8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "feeds", sa.JSON(), nullable=True,
            comment=(
                "For a creator's own collection, the refs of the creator's feeds its link lists, such as only a YouTube "
                "channel's Videos; null lists all that its link lists"
            ),
        ))
    mains = "SELECT main_collection_id FROM creator_accounts WHERE main_collection_id IS NOT NULL"
    bind = op.get_bind()
    bind.execute(sa.text(f"UPDATE collections SET feeds = '[]' WHERE outside_videos = 'only' AND id IN ({mains})"))
    bind.execute(sa.text(
        f"UPDATE collections SET outside_videos = 'add' WHERE outside_videos = 'only' AND type = 'music' AND id IN ({mains})"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE collections SET outside_videos = 'only' WHERE feeds = '[]'"))
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("feeds")
