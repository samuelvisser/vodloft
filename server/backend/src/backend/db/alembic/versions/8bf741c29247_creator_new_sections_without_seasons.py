"""Creators whose Sites can't make lists seasons add new sections as collections

A creator whose accounts are all on a Site whose lists can't be seasons, such as a Daily Wire host, no longer offers
"Add it as a season" for new shows. Such a creator already made each new show a collection of its own, so the setting
becomes that.

Revision ID: 8bf741c29247
Revises: a91a97a6c374
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8bf741c29247"
down_revision = "a91a97a6c374"
branch_labels = None
depends_on = None

# The Sites whose lists could be seasons of a creator's own collection when this migration was written.
_SEASON_SITES = ("youtube", "bandcamp", "soundcloud")


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "UPDATE creators SET new_sections = 'own' WHERE new_sections = 'season' AND NOT EXISTS ("
        " SELECT 1 FROM creator_accounts WHERE creator_accounts.creator_id = creators.id"
        " AND creator_accounts.site_key IN :sites)"
    ).bindparams(sa.bindparam("sites", expanding=True)), {"sites": list(_SEASON_SITES)})


def downgrade() -> None:
    # The creators that had "season" can't be told from the ones that chose "own".
    pass
