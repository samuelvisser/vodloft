"""Source-owned Domain declarations and verified connection capabilities.

Revision ID: 7b51c8d09a63
Revises: 6e7a9d13c2f0
"""
from alembic import op
import sqlalchemy as sa

revision = '7b51c8d09a63'
down_revision = '6e7a9d13c2f0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_source_domains') as batch:
        batch.add_column(sa.Column('aliases', sa.JSON, nullable=False, server_default='[]'))
        batch.add_column(sa.Column('capabilities', sa.JSON, nullable=True))
        batch.add_column(sa.Column('catalogue_revision', sa.String, nullable=True))
    with op.batch_alter_table('vodloft_source_connections') as batch:
        batch.add_column(sa.Column('capabilities', sa.JSON, nullable=True))
        batch.add_column(sa.Column('domain_capabilities', sa.JSON, nullable=False, server_default='{}'))
        batch.add_column(sa.Column('authenticated', sa.Boolean, nullable=True))
        batch.add_column(sa.Column('last_capability_check_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('vodloft_source_connections') as batch:
        for name in ('capabilities', 'domain_capabilities', 'authenticated', 'last_capability_check_at'):
            batch.drop_column(name)
    with op.batch_alter_table('vodloft_source_domains') as batch:
        for name in ('aliases', 'capabilities', 'catalogue_revision'):
            batch.drop_column(name)
