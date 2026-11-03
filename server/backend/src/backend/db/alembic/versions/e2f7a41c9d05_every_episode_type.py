"""A Download Profile without episode types downloads every type.

Before, a Download Profile with an empty episode type list downloaded nothing.
The episode types line can now be removed, which means every type, so those
profiles stop downloading automatically instead of starting to download
everything.

Revision ID: e2f7a41c9d05
Revises: b5e1c0a7d392
Create Date: 2026-11-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e2f7a41c9d05"
down_revision = "b5e1c0a7d392"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE download_profiles SET enable_profile = 0 "
        "WHERE ep_id_type_list IS NULL OR json_array_length(ep_id_type_list) = 0"
    ))


def downgrade() -> None:
    pass
