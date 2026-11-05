"""RSS feeds proxy their Site's video through VODLoft by default.

YouTube's direct links stop working before an app is done with them, so feeds of YouTube now pass the
video on through VODLoft unless the feed is set otherwise. Existing feeds of YouTube move to it too:
they had it off only because that was the default. Other Sites have no choice, so it changes nothing there.

Revision ID: 28c70478078a
Revises: d6346ad993ee
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "28c70478078a"
down_revision = "d6346ad993ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.alter_column("proxy_source_stream", existing_type=sa.Boolean(), existing_nullable=False, server_default="1")
    op.get_bind().execute(sa.text("UPDATE stream_profiles_rss SET proxy_source_stream = 1"))


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.alter_column("proxy_source_stream", existing_type=sa.Boolean(), existing_nullable=False, server_default="0")
