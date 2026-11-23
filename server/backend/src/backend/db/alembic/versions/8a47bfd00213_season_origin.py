"""Each season knows where it came from: its Site's own, one of the Site's lists, or made by VODLoft.

Existing seasons are sorted out by what they are now:
- a season a list fills, or the one season of a collection made from one list, came from a list;
- on The Daily Wire and NPO Start, whose Sources have seasons of their own, any other season that is not one VODLoft
  makes itself (the season of what is in no list, or a season per year) came from the Site;
- every other season VODLoft made.

Revision ID: 8a47bfd00213
Revises: e3d9539a8be1
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "8a47bfd00213"
down_revision = "e3d9539a8be1"
branch_labels = None
depends_on = None

# The Sources that had seasons of their own when this migration was written.
_OWN_SEASON_SOURCES = ("dailywire", "npo")

# A season per year is known by its slug, its four-digit year.
_NOT_A_YEAR = "NOT (length(s.slug) = 4 AND s.slug NOT GLOB '*[^0-9]*')"
_NOT_A_YEAR_PG = "NOT (s.slug ~ '^[0-9]{4}$')"


def upgrade() -> None:
    op.add_column("seasons", sa.Column(
        "origin", sa.String(), nullable=False, server_default="vodloft",
        comment="Where the season came from: the Site's own (site), one of its lists (list), or made by VODLoft (vodloft)",
    ))
    bind = op.get_bind()
    not_a_year = _NOT_A_YEAR_PG if bind.dialect.name == "postgresql" else _NOT_A_YEAR
    bind.execute(sa.text(
        "UPDATE seasons SET origin = 'list' WHERE id IN "
        "(SELECT season_id FROM collection_lists WHERE season_id IS NOT NULL)"
    ))
    bind.execute(sa.text(
        "UPDATE seasons SET origin = 'list' WHERE id IN (SELECT s.id FROM seasons s JOIN collections c "
        "ON c.id = s.collection_id WHERE c.kind = 'list' AND c.sharing_url IS NOT NULL "
        f"AND s.season_type = 'normal' AND NOT s.loose AND {not_a_year})"
    ))
    bind.execute(
        sa.text(
            "UPDATE seasons SET origin = 'site' WHERE origin = 'vodloft' AND id IN (SELECT s.id FROM seasons s "
            f"JOIN collections c ON c.id = s.collection_id WHERE c.source_key IN :sources AND NOT s.loose AND {not_a_year})"
        ).bindparams(sa.bindparam("sources", expanding=True)),
        {"sources": list(_OWN_SEASON_SOURCES)},
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("seasons") as batch:
            batch.drop_column("origin")
    else:
        op.drop_column("seasons", "origin")
