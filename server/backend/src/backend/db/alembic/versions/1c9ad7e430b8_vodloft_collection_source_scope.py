"""Keep Collection occurrence identities separate across linked Sources.

Revision ID: 1c9ad7e430b8
Revises: f6bc4309d175
"""
from alembic import op
import sqlalchemy as sa

revision = '1c9ad7e430b8'
down_revision = 'f6bc4309d175'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vodloft_collection_entries', sa.Column('source_id', sa.String, nullable=True))
    # Before explicit cross-Source linking, a Collection's references all came
    # from one Source. Account variants share that Source's occurrence namespace.
    op.get_bind().execute(sa.text('''
        UPDATE vodloft_collection_entries SET source_id = (
            SELECT MIN(source_id) FROM vodloft_source_references
            WHERE item_id = vodloft_collection_entries.collection_id
        )
    '''))
    with op.batch_alter_table('vodloft_collection_entries') as batch:
        batch.drop_constraint('uq_vodloft_collection_entry_occurrence', type_='unique')
        batch.create_unique_constraint('uq_vodloft_collection_source_occurrence',
            ['collection_id', 'source_id', 'occurrence_key'])


def downgrade():
    # The older schema cannot represent Source-local duplicate occurrences.
    # Refuse this downgrade instead of discarding relationships or changing IDs.
    duplicate = op.get_bind().execute(sa.text('''
        SELECT collection_id FROM vodloft_collection_entries
        WHERE occurrence_key IS NOT NULL
        GROUP BY collection_id, occurrence_key HAVING COUNT(*) > 1
        LIMIT 1
    ''')).first()
    if duplicate:
        raise RuntimeError('Linked Sources have duplicate occurrence IDs; the older schema cannot preserve them')
    with op.batch_alter_table('vodloft_collection_entries') as batch:
        batch.drop_constraint('uq_vodloft_collection_source_occurrence', type_='unique')
        batch.create_unique_constraint('uq_vodloft_collection_entry_occurrence',
            ['collection_id', 'occurrence_key'])
        batch.drop_column('source_id')
