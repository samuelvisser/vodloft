"""Durable Collection scan sessions and account-scoped membership.

Revision ID: 6e7a9d13c2f0
Revises: 2be60a847fc1
"""
from alembic import op
import sqlalchemy as sa

revision = '6e7a9d13c2f0'
down_revision = '2be60a847fc1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_collection_entries') as batch:
        batch.add_column(sa.Column('connection_id', sa.Integer, nullable=True))
        batch.add_column(sa.Column('connection_key', sa.Integer, nullable=False, server_default='0'))
        batch.add_column(sa.Column('active', sa.Boolean, nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('last_seen_scan_key', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_vodloft_entry_connection', 'vodloft_source_connections', ['connection_id'], ['id'])
        batch.drop_constraint('uq_vodloft_collection_source_occurrence', type_='unique')
        batch.create_unique_constraint('uq_vodloft_collection_connection_occurrence',
            ['collection_id', 'source_id', 'connection_key', 'occurrence_key'])
    connection = op.get_bind()
    entries = sa.table('vodloft_collection_entries', sa.column('id', sa.Integer),
        sa.column('collection_id', sa.Integer), sa.column('item_id', sa.Integer),
        sa.column('source_id', sa.String), sa.column('connection_id', sa.Integer),
        sa.column('connection_key', sa.Integer), sa.column('occurrence_key', sa.String),
        sa.column('position', sa.Integer), sa.column('group', sa.String),
        sa.column('episode_number', sa.String), sa.column('role', sa.String))
    references = sa.table('vodloft_source_references', sa.column('item_id', sa.Integer),
        sa.column('source_id', sa.String), sa.column('connection_id', sa.Integer))
    # Old memberships were shared across accounts. Preserve that existing view
    # for each known parent connection; subsequent authoritative scans reconcile
    # each account separately. Manual, Source-less membership stays unscoped.
    for entry in connection.execute(sa.select(entries)).mappings().all():
        if entry['source_id'] is None:
            continue
        accounts = list(dict.fromkeys(connection.execute(sa.select(references.c.connection_id).where(
            references.c.item_id == entry['collection_id'], references.c.source_id == entry['source_id'])).scalars()))
        for index, account in enumerate(accounts):
            if index == 0:
                connection.execute(entries.update().where(entries.c.id == entry['id']).values(
                    connection_id=account, connection_key=account or 0))
            else:
                values = {key: value for key, value in entry.items() if key != 'id'}
                values.update(connection_id=account, connection_key=account or 0)
                connection.execute(entries.insert().values(**values))
    with op.batch_alter_table('vodloft_collection_scans') as batch:
        batch.add_column(sa.Column('scan_key', sa.String(36), nullable=True))
        batch.add_column(sa.Column('source_reference_id', sa.Integer, nullable=True))
        batch.add_column(sa.Column('active_reference_id', sa.Integer, nullable=True))
        batch.add_column(sa.Column('mode', sa.String(16), nullable=False, server_default='full'))
        batch.add_column(sa.Column('status', sa.String(16), nullable=False, server_default='partial'))
        batch.add_column(sa.Column('lease_owner', sa.String(36), nullable=True))
        batch.add_column(sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('command_fingerprint', sa.String(64), nullable=True))
        batch.add_column(sa.Column('connection_fingerprint', sa.String(64), nullable=True))
        batch.add_column(sa.Column('removed_count', sa.Integer, nullable=False, server_default='0'))
        batch.add_column(sa.Column('operation_id', sa.String(64), nullable=True))
        batch.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.create_foreign_key('fk_vodloft_scan_reference', 'vodloft_source_references', ['source_reference_id'], ['id'])
        batch.create_foreign_key('fk_vodloft_scan_active_reference', 'vodloft_source_references', ['active_reference_id'], ['id'])
        batch.create_unique_constraint('uq_vodloft_active_collection_scan', ['active_reference_id'])
    scans = sa.table('vodloft_collection_scans', sa.column('complete', sa.Boolean), sa.column('status', sa.String))
    connection.execute(scans.update().where(scans.c.complete.is_(True)).values(status='complete'))


def downgrade():
    connection = op.get_bind()
    entries = sa.table('vodloft_collection_entries', sa.column('collection_id', sa.Integer),
        sa.column('source_id', sa.String), sa.column('occurrence_key', sa.String))
    duplicate = connection.execute(sa.select(sa.func.count()).select_from(entries).where(
        entries.c.occurrence_key.is_not(None)).group_by(entries.c.collection_id,
        entries.c.source_id, entries.c.occurrence_key).having(sa.func.count() > 1)).first()
    if duplicate:
        raise RuntimeError('Account-specific memberships cannot be collapsed safely; restore a backup to downgrade')
    with op.batch_alter_table('vodloft_collection_scans') as batch:
        batch.drop_constraint('uq_vodloft_active_collection_scan', type_='unique')
        batch.drop_constraint('fk_vodloft_scan_reference', type_='foreignkey')
        batch.drop_constraint('fk_vodloft_scan_active_reference', type_='foreignkey')
        for name in ('scan_key', 'source_reference_id', 'active_reference_id', 'mode', 'status',
                     'lease_owner', 'lease_expires_at', 'command_fingerprint', 'connection_fingerprint',
                     'removed_count', 'operation_id', 'updated_at'):
            batch.drop_column(name)
    with op.batch_alter_table('vodloft_collection_entries') as batch:
        batch.drop_constraint('uq_vodloft_collection_connection_occurrence', type_='unique')
        batch.drop_constraint('fk_vodloft_entry_connection', type_='foreignkey')
        for name in ('connection_id', 'connection_key', 'active', 'last_seen_scan_key'):
            batch.drop_column(name)
        batch.create_unique_constraint('uq_vodloft_collection_source_occurrence',
            ['collection_id', 'source_id', 'occurrence_key'])
