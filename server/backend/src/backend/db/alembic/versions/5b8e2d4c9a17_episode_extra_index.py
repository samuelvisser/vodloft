"""Number every collection's extras with VODLoft's own extra index.

Revision ID: 5b8e2d4c9a17
Revises: 12c4ec47817e
Create Date: 2026-11-18

An extra is an episode of an Extras season or of a type other than ep. A collection's extras are numbered
together, in the order of their episode index.
"""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op


revision = "5b8e2d4c9a17"
down_revision = "12c4ec47817e"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("extra_index")
