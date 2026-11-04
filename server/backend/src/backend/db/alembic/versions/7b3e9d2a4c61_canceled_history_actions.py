"""Spell canceled download history actions the way the rest of VODLoft does.

Revision ID: 7b3e9d2a4c61
Revises: c89f1a5ea2ba
Create Date: 2026-11-04

Library download history stored "cancelled"; tasks, operations and quick downloads
store "canceled". The history now uses "canceled" too.
"""
from __future__ import annotations

from alembic import op

revision = "7b3e9d2a4c61"
down_revision = "c89f1a5ea2ba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE media_download_history SET action = 'canceled' WHERE action = 'cancelled'")


def downgrade() -> None:
    op.execute("UPDATE media_download_history SET action = 'cancelled' WHERE action = 'canceled'")
