"""Sites in the order VODLoft got them, and the Sites VODLoft used to always list as ordinary Sites.

Every list of Sites shows them in the order they were added, so each Site gets a position; the Sites an installation
already has are numbered by name. The Daily Wire, NPO Start and YouTube, which VODLoft used to list without a row,
become ordinary Site rows, so the user can remove them like any other Site. A new VODLoft gets its default Sites from
the initial seed.

Revision ID: 710584a17632
Revises: 7c41e2a9d5b3
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "710584a17632"
down_revision = "7c41e2a9d5b3"
branch_labels = None
depends_on = None

COMMENT = "Where the Site comes in lists of Sites: the order VODLoft got them in"

# As the Sources named them when this migration was written.
ALWAYS_LISTED = (
    {"key": "dailywire", "name": "The Daily Wire", "domains": ["dailywire.com"]},
    {"key": "npo", "name": "NPO Start", "domains": ["npo.nl"]},
    {"key": "youtube", "name": "YouTube", "domains": ["youtube.com"]},
)

sites = sa.table(
    "sites", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("domains", sa.JSON),
    sa.column("position", sa.Integer),
)


def upgrade() -> None:
    op.add_column("sites", sa.Column("position", sa.Integer(), nullable=False, server_default="0", comment=COMMENT))
    bind = op.get_bind()
    existing = set(bind.execute(sa.select(sites.c.key)).scalars())
    missing = [site for site in ALWAYS_LISTED if site["key"] not in existing]
    if missing:
        op.bulk_insert(sites, missing)
    keys = bind.execute(sa.select(sites.c.key).order_by(sa.func.lower(sites.c.name), sites.c.key)).scalars().all()
    for position, key in enumerate(keys, start=1):
        bind.execute(sa.update(sites).where(sites.c.key == key).values(position=position))


def downgrade() -> None:
    # The added rows stay: a Site row is what VODLoft has seen, which the earlier schema keeps too.
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("position")
