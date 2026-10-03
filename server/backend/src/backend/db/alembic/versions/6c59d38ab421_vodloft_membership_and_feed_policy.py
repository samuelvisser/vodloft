"""Generic group selection, member roles and feed publication limits.

Revision ID: 6c59d38ab421
Revises: 38bcde60a714
"""
from alembic import op
import sqlalchemy as sa

revision = '6c59d38ab421'
down_revision = '38bcde60a714'
branch_labels = None
depends_on = None


def upgrade():
    for table in ['vodloft_collection_download_profiles', 'vodloft_collection_stream_profiles']:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('selected_groups', sa.JSON, nullable=True))
            batch.add_column(sa.Column('known_groups', sa.JSON, nullable=False, server_default='[]'))
            batch.add_column(sa.Column('include_future_groups', sa.Boolean, nullable=False, server_default='1'))
            batch.add_column(sa.Column('member_roles', sa.JSON, nullable=True))
    with op.batch_alter_table('vodloft_collection_stream_profiles') as batch:
        batch.add_column(sa.Column('max_items', sa.Integer, nullable=False, server_default='0'))
        batch.add_column(sa.Column('feed_title', sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table('vodloft_collection_stream_profiles') as batch:
        batch.drop_column('feed_title')
        batch.drop_column('max_items')
    for table in ['vodloft_collection_stream_profiles', 'vodloft_collection_download_profiles']:
        with op.batch_alter_table(table) as batch:
            for column in ['member_roles', 'include_future_groups', 'known_groups', 'selected_groups']:
                batch.drop_column(column)
