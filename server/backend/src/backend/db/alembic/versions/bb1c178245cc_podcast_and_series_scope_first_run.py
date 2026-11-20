"""Where "Podcasts and Series" was first renamed to podcast-and-series

Test databases ran the rename at this revision, straight after 5e0c7a2b91d4, before the new list and section type
migrations joined the history. Keeping this revision where they ran it, ahead of those migrations, lets those
databases still run them; the rename itself now happens in f3df05c49000, which finds nothing left to rename there.

Revision ID: bb1c178245cc
Revises: 5e0c7a2b91d4
Create Date: 2026-11-19
"""
from __future__ import annotations

revision = "bb1c178245cc"
down_revision = "5e0c7a2b91d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
