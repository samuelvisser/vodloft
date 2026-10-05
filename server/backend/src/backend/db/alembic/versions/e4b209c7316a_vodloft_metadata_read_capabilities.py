"""Retain metadata reads on existing built-in Source references.

Revision ID: e4b209c7316a
Revises: a62743e90b15
"""
from alembic import op
import sqlalchemy as sa

revision = 'e4b209c7316a'
down_revision = 'a62743e90b15'
branch_labels = None
depends_on = None

_SOURCES = ('yt-dlp', 'dailywire')
_READS = {'resolve_url', 'inspect_media'}


def upgrade():
    connection = op.get_bind()
    references = sa.table('vodloft_source_references', sa.column('id', sa.Integer),
        sa.column('source_id', sa.String), sa.column('capabilities', sa.JSON))
    for row in connection.execute(sa.select(references.c.id, references.c.capabilities)
            .where(references.c.source_id.in_(_SOURCES))).mappings():
        if row['capabilities'] is not None:
            capabilities = sorted(set(row['capabilities']) | _READS)
            connection.execute(references.update().where(references.c.id == row['id'])
                .values(capabilities=capabilities))
    snapshots = sa.table('vodloft_source_snapshots', sa.column('id', sa.Integer),
        sa.column('source_id', sa.String), sa.column('metadata_snapshot', sa.JSON))
    for row in connection.execute(sa.select(snapshots).where(snapshots.c.source_id.in_(_SOURCES))).mappings():
        metadata = dict(row['metadata_snapshot'])
        # Do not materialize omitted metadata or replace an unknown capability set.
        if metadata.get('capabilities') is not None:
            metadata['capabilities'] = sorted(set(metadata['capabilities']) | _READS)
        for field in ('entries', 'extras'):
            if field in metadata:
                children = []
                for entry in metadata[field]:
                    child = dict(entry)
                    if child.get('reference', {}).get('source_id') == row['source_id'] and child.get('capabilities') is not None:
                        child['capabilities'] = sorted(set(child['capabilities']) | _READS)
                    children.append(child)
                metadata[field] = children
        connection.execute(snapshots.update().where(snapshots.c.id == row['id'])
            .values(metadata_snapshot=metadata))


def downgrade():
    # These are valid Source facts, including declarations from newer snapshots.
    # Removing them would also discard capabilities not introduced by this upgrade.
    pass
