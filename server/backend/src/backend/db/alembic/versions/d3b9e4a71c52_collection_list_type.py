"""Collections remember which type of list their link is.

Revision ID: d3b9e4a71c52
Revises: 8a47bfd00213
Create Date: 2026-11-23

On SoundCloud an album and a playlist both have a set's link, so a collection of one couldn't say which it is. A
collection of one list now keeps the type of list its Site gives when its link is looked up. A background migration
looks it up for the collections there already are.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "d3b9e4a71c52"
down_revision = "8a47bfd00213"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collections", sa.Column(
        "list_type", sa.String(), nullable=True,
        comment="The key of its Site's type of list its link is, such as album or playlist on SoundCloud, where the "
                "Site has several types its links don't tell apart",
    ))


def downgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("list_type")
