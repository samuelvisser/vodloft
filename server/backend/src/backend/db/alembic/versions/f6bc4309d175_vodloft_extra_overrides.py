"""Preserve explicit Movie Extra parent and type choices across Source refreshes.

Revision ID: f6bc4309d175
Revises: 8daf391ac2eb
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6bc4309d175'
down_revision = '8daf391ac2eb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vodloft_media_items', sa.Column('user_parent_ids', sa.JSON, nullable=True))
    op.add_column('vodloft_media_items', sa.Column('user_extra_type', sa.String(32), nullable=True))


def downgrade():
    op.drop_column('vodloft_media_items', 'user_extra_type')
    op.drop_column('vodloft_media_items', 'user_parent_ids')
