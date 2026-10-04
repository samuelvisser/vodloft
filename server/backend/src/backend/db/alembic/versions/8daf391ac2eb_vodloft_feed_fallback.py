"""Explicit portable rendition fallback for Stream Profiles.

Revision ID: 8daf391ac2eb
Revises: 79a520ced413
"""
from alembic import op
import sqlalchemy as sa
revision = '8daf391ac2eb'
down_revision = '79a520ced413'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vodloft_collection_stream_profiles', sa.Column('allow_other_renditions',
        sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('vodloft_collection_stream_profiles', 'allow_other_renditions')
