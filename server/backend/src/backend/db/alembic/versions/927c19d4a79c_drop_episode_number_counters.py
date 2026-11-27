"""Collections no longer keep counters of the trailer, auxiliary and date numbers they gave out: every Source's episodes
are numbered after the identifiers the collection has.

Revision ID: 927c19d4a79c
Revises: c41e7d09b2a8
Create Date: 2026-11-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "927c19d4a79c"
down_revision = "c41e7d09b2a8"
branch_labels = None
depends_on = None

_COUNTERS = ("ep_id.latest_aux_num", "ep_id.latest_trailer_num", "ep_id.latest_ep_date")


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM metadata WHERE parent_table = 'collections' AND key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True),
        ),
        {"keys": list(_COUNTERS)},
    )


def downgrade() -> None:
    # The counters only ever ran ahead of the identifiers; numbering after the identifiers is what they gave too.
    pass
