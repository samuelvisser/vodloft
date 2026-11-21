"""The Sites VODLoft starts with, The Daily Wire, NPO Start and YouTube, become ordinary Site rows, so the user can
remove them like any other Site. An installation gets a row for each one it does not have yet.

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

# As the Sources name them when this migration was written.
BUILTIN_SITES = (
    {"key": "dailywire", "name": "The Daily Wire", "domains": ["dailywire.com"]},
    {"key": "npo", "name": "NPO Start", "domains": ["npo.nl"]},
    {"key": "youtube", "name": "YouTube", "domains": ["youtube.com"]},
)

sites = sa.table("sites", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("domains", sa.JSON))


def upgrade() -> None:
    existing = set(op.get_bind().execute(sa.select(sites.c.key)).scalars())
    missing = [site for site in BUILTIN_SITES if site["key"] not in existing]
    if missing:
        op.bulk_insert(sites, missing)


def downgrade() -> None:
    # The rows stay: a Site row is what VODLoft has seen, which the earlier schema keeps too.
    pass
