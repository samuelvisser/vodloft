"""Join the two develop migrations: unplayable formats on media, and a creator's own yt-dlp options.

Both were made after a4318a92a5ca on their own branches. This revision changes nothing; it only makes them one
history again, so a database that already ran either of them upgrades as usual.

Revision ID: 837085288aa0
Revises: ac034d79c796, 5c1e8b7d3f20
Create Date: 2026-11-23
"""
from __future__ import annotations


revision = "837085288aa0"
down_revision = ("ac034d79c796", "5c1e8b7d3f20")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
