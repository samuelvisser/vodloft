"""A Collection profile available for podcasts and series stores that as podcast-and-series

The Available for choice "Podcasts and Series" was stored as "both". It is now stored as "podcast-and-series".

Revision ID: bb1c178245cc
Revises: 7d3b9e41a6c2
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bb1c178245cc"
down_revision = "7d3b9e41a6c2"
branch_labels = None
depends_on = None


def _rename(old: str, new: str) -> None:
    op.execute(f"UPDATE local_media_profiles_collection SET collection_scope = '{new}' WHERE collection_scope = '{old}'")
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.alter_column("collection_scope", existing_type=sa.String(), existing_nullable=False, server_default=new)


def upgrade() -> None:
    _rename("both", "podcast-and-series")


def downgrade() -> None:
    _rename("podcast-and-series", "both")
