"""Store availability under its Source/account reference, not canonical metadata.

Revision ID: 2be60a847fc1
Revises: 1c9ad7e430b8
"""
from collections import defaultdict
from alembic import op
import sqlalchemy as sa

revision = '2be60a847fc1'
down_revision = '1c9ad7e430b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vodloft_source_references', sa.Column('capabilities', sa.JSON, nullable=True))
    op.add_column('vodloft_source_references', sa.Column('formats', sa.JSON, nullable=True))
    connection = op.get_bind()
    references = sa.table('vodloft_source_references', sa.column('id', sa.Integer),
        sa.column('item_id', sa.Integer), sa.column('source_id', sa.String),
        sa.column('connection_id', sa.Integer), sa.column('capabilities', sa.JSON), sa.column('formats', sa.JSON))
    items = sa.table('vodloft_media_items', sa.column('id', sa.Integer),
        sa.column('capabilities', sa.JSON), sa.column('formats', sa.JSON))
    snapshots = sa.table('vodloft_source_snapshots', sa.column('id', sa.Integer),
        sa.column('item_id', sa.Integer), sa.column('source_id', sa.String),
        sa.column('connection_id', sa.Integer), sa.column('metadata_snapshot', sa.JSON))
    rows = connection.execute(sa.select(references)).mappings().all()
    counts = defaultdict(int)
    for reference in rows:
        counts[reference['item_id']] += 1
    canonical = {item['id']: item for item in connection.execute(sa.select(items)).mappings()}
    scoped = defaultdict(dict)
    for snapshot in connection.execute(sa.select(snapshots).order_by(snapshots.c.id.desc())).mappings():
        values = scoped[(snapshot['item_id'], snapshot['source_id'], snapshot['connection_id'])]
        for name in ('capabilities', 'formats'):
            if name not in values and name in snapshot['metadata_snapshot']:
                values[name] = snapshot['metadata_snapshot'][name]
    updates = []
    for reference in rows:
        values = dict(scoped[(reference['item_id'], reference['source_id'], reference['connection_id'])])
        # Lightweight entries have no detailed snapshot. Canonical availability
        # is attributable only when exactly one Source/account reference exists.
        if counts[reference['item_id']] == 1:
            for name in ('capabilities', 'formats'):
                values.setdefault(name, canonical[reference['item_id']][name])
        updates.append({'ref_id': reference['id'], 'ref_capabilities': values.get('capabilities'),
            'ref_formats': values.get('formats')})
    if updates:
        connection.execute(references.update().where(references.c.id == sa.bindparam('ref_id')).values(
            capabilities=sa.bindparam('ref_capabilities'), formats=sa.bindparam('ref_formats')), updates)


def downgrade():
    op.drop_column('vodloft_source_references', 'formats')
    op.drop_column('vodloft_source_references', 'capabilities')
