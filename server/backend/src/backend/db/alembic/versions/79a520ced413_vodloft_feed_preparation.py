"""Explicit Source routing and local representation for feed preparation.

Revision ID: 79a520ced413
Revises: 6c59d38ab421
"""
from alembic import op
import sqlalchemy as sa

revision = '79a520ced413'
down_revision = '6c59d38ab421'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_collection_stream_profiles') as batch:
        batch.add_column(sa.Column('source_reference_id', sa.Integer, nullable=True))
        batch.create_foreign_key('fk_vodloft_stream_source', 'vodloft_source_references', ['source_reference_id'], ['id'])
        batch.add_column(sa.Column('local_profile_ids', sa.JSON, nullable=False, server_default='[]'))
        batch.add_column(sa.Column('refresh_minutes', sa.Integer, nullable=False, server_default='60'))
        batch.add_column(sa.Column('last_scan_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('vodloft_collection_stream_profiles') as batch:
        batch.drop_column('last_scan_at')
        batch.drop_column('refresh_minutes')
        batch.drop_column('local_profile_ids')
        batch.drop_constraint('fk_vodloft_stream_source', type_='foreignkey')
        batch.drop_column('source_reference_id')
