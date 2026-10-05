"""Bounded, durable Collection synchronization retry policy.

Revision ID: 91da62e80f47
Revises: 7b51c8d09a63
"""
from alembic import op
import sqlalchemy as sa

revision = '91da62e80f47'
down_revision = '7b51c8d09a63'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_collection_scans') as batch:
        batch.add_column(sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('error_code', sa.String(32), nullable=True))
        batch.add_column(sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('vodloft_collection_scans') as batch:
        batch.drop_column('retry_at')
        batch.drop_column('error_code')
        batch.drop_column('attempts')
        batch.drop_column('failure_count')
