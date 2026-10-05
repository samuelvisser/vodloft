"""Complete existing local scan history with unambiguous reference provenance.

Revision ID: a62743e90b15
Revises: 91da62e80f47
"""
from alembic import op
import hashlib
import json
import sqlalchemy as sa

revision = 'a62743e90b15'
down_revision = '91da62e80f47'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vodloft_source_connections') as batch:
        batch.add_column(sa.Column('scope_revision', sa.Integer(), nullable=False, server_default='1'))
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE vodloft_collection_scans SET status = 'complete' WHERE complete = true AND status = 'partial'"))
    rows = connection.execute(sa.text('''
        SELECT scan.id, MIN(reference.id) AS reference_id
        FROM vodloft_collection_scans AS scan
        JOIN vodloft_source_references AS reference ON reference.item_id = scan.collection_id
          AND reference.source_id = scan.source_id
          AND reference.connection_key = COALESCE(scan.connection_id, 0)
        WHERE scan.source_reference_id IS NULL
        GROUP BY scan.id HAVING COUNT(reference.id) = 1
    '''))
    values = [dict(row._mapping) for row in rows]
    if values:
        connection.execute(sa.text('UPDATE vodloft_collection_scans SET source_reference_id = :reference_id WHERE id = :id'), values)
    jobs = sa.table('vodloft_acquisition_jobs', sa.column('id', sa.Integer()), sa.column('reference_id', sa.Integer()),
        sa.column('execution_spec', sa.JSON()))
    references = sa.table('vodloft_source_references', sa.column('id', sa.Integer()), sa.column('source_id', sa.String()),
        sa.column('connection_id', sa.Integer()), sa.column('connection_key', sa.Integer()))
    accounts = sa.table('vodloft_source_connections', sa.column('id', sa.Integer()), sa.column('scope_revision', sa.Integer()))
    artifacts = sa.table('vodloft_artifacts', sa.column('source_reference_id', sa.Integer()), sa.column('representation_key', sa.String()))
    rows = list(connection.execute(sa.select(jobs.c.id, jobs.c.reference_id, jobs.c.execution_spec,
        references.c.source_id, references.c.connection_id, references.c.connection_key, accounts.c.scope_revision)
        .select_from(jobs.join(references, references.c.id == jobs.c.reference_id)
            .outerjoin(accounts, accounts.c.id == references.c.connection_id))))
    for row in rows:
        spec = dict(row.execution_spec or {})
        scope = hashlib.sha256(json.dumps([row.source_id, row.connection_id, row.scope_revision]).encode()).hexdigest()
        spec['connection_scope'] = scope
        old_key = spec.get('representation_key')
        if old_key and all(key in spec for key in ('source_reference', 'representation', 'preferred_format', 'values')) and 'media_type' in spec['values']:
            reference = spec['source_reference']
            policy = spec['representation']
            metadata = spec.get('metadata', {})
            new_key = hashlib.sha256(json.dumps({
                'source_id': row.source_id, 'namespace': reference['namespace'], 'upstream_id': reference['upstream_id'],
                'connection_key': row.connection_key, 'connection_scope': scope,
                'format': spec['preferred_format'], 'media_type': spec['values']['media_type'], 'representation': policy,
                'metadata': {'title': metadata.get('title', ''), 'description': metadata.get('description', '')}
                    if policy.get('embed_metadata', True) else {},
            }, sort_keys=True).encode()).hexdigest()
            connection.execute(artifacts.update().where(artifacts.c.source_reference_id == row.reference_id,
                artifacts.c.representation_key == old_key).values(representation_key=new_key))
            spec['representation_key'] = new_key
        connection.execute(jobs.update().where(jobs.c.id == row.id).values(execution_spec=spec))


def downgrade():
    # These provenance facts and completion flags remain valid on the older schema.
    with op.batch_alter_table('vodloft_source_connections') as batch:
        batch.drop_column('scope_revision')
