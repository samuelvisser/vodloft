"""Keep stable Collection occurrences without using playlist position as identity.

Revision ID: b13c80e9a7d4
Revises: a92e7b14c6f0
"""
from alembic import op
import sqlalchemy as sa

revision = "b13c80e9a7d4"
down_revision = "a92e7b14c6f0"
branch_labels = None
depends_on = None

_names = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    with op.batch_alter_table("vodloft_collection_entries", naming_convention=_names) as batch:
        batch.add_column(sa.Column("occurrence_key", sa.String, nullable=True))
        batch.drop_constraint("uq_vodloft_collection_entries_collection_id", type_="unique")
        batch.create_unique_constraint("uq_vodloft_collection_entry_occurrence", ["collection_id", "occurrence_key"])


def downgrade():
    # Duplicate occurrences must be resolved explicitly before reverting this schema.
    with op.batch_alter_table("vodloft_collection_entries", naming_convention=_names) as batch:
        batch.drop_constraint("uq_vodloft_collection_entry_occurrence", type_="unique")
        batch.drop_column("occurrence_key")
        batch.create_unique_constraint("uq_vodloft_collection_entries_collection_id", ["collection_id", "item_id"])
