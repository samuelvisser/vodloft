"""Explicit media-server user identities and RSS delivery ownership.

Revision ID: 38bcde60a714
Revises: 981c24fe36da
"""
from alembic import op
import sqlalchemy as sa

revision = '38bcde60a714'
down_revision = '981c24fe36da'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_feed_subscriptions') as batch:
        batch.add_column(sa.Column('integration_target_id', sa.Integer, nullable=True))
        batch.create_foreign_key('fk_vodloft_feed_integration', 'vodloft_media_server_targets', ['integration_target_id'], ['id'])
    op.create_table('vodloft_integration_user_mappings',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('target_id', sa.Integer, sa.ForeignKey('vodloft_media_server_targets.id'), nullable=False),
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('remote_user_id', sa.String(120), nullable=False),
        sa.Column('secret_ciphertext', sa.String, nullable=False),
        sa.UniqueConstraint('target_id', 'user_key'))
    op.create_table('vodloft_integration_feed_deliveries',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('target_id', sa.Integer, sa.ForeignKey('vodloft_media_server_targets.id'), nullable=False),
        sa.Column('subscription_id', sa.Integer, sa.ForeignKey('vodloft_feed_subscriptions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('folder_id', sa.String(120), nullable=False),
        sa.Column('server_path', sa.String, nullable=False), sa.Column('feed_url', sa.String, nullable=False),
        sa.Column('remote_id', sa.String(120), nullable=True), sa.Column('state', sa.String(24), nullable=False),
        sa.Column('error', sa.String, nullable=True), sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('target_id', 'subscription_id'))
    op.create_table('vodloft_integration_feed_items',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('delivery_id', sa.Integer, sa.ForeignKey('vodloft_integration_feed_deliveries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', sa.Integer, sa.ForeignKey('vodloft_media_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('remote_episode_id', sa.String(120), nullable=False), sa.Column('available', sa.Boolean, nullable=False),
        sa.UniqueConstraint('delivery_id', 'item_id'))


def downgrade():
    op.drop_table('vodloft_integration_feed_items')
    op.drop_table('vodloft_integration_feed_deliveries')
    op.drop_table('vodloft_integration_user_mappings')
    with op.batch_alter_table('vodloft_feed_subscriptions') as batch:
        batch.drop_constraint('fk_vodloft_feed_integration', type_='foreignkey')
        batch.drop_column('integration_target_id')
