"""Bind playback to local users and freeze queued Source identity.

Revision ID: 981c24fe36da
Revises: fba129de530c
"""
import json
from alembic import op
import sqlalchemy as sa

revision = "981c24fe36da"
down_revision = "fba129de530c"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_playback_sessions") as batch:
        batch.add_column(sa.Column("user_key", sa.String(80), nullable=False, server_default="admin"))
    # Existing leases predate ownership and must be replaced by an authenticated watch request.
    op.execute("DELETE FROM vodloft_playback_segments")
    op.execute("DELETE FROM vodloft_playback_sessions")
    connection = op.get_bind()
    rows = connection.execute(sa.text("""SELECT j.id, j.execution_spec, r.source_id,
        r.namespace, r.upstream_id, r.url, d.hostname FROM vodloft_acquisition_jobs j
        JOIN vodloft_source_references r ON r.id = j.reference_id
        JOIN vodloft_domains d ON d.id = r.domain_id WHERE j.execution_spec IS NOT NULL""")).mappings()
    for row in rows:
        spec = json.loads(row["execution_spec"]) if isinstance(row["execution_spec"], str) else dict(row["execution_spec"])
        spec["source_reference"] = {"source_id": row["source_id"], "domain": row["hostname"],
            "namespace": row["namespace"], "upstream_id": row["upstream_id"], "url": row["url"]}
        connection.execute(sa.text("UPDATE vodloft_acquisition_jobs SET execution_spec=:spec WHERE id=:id"),
            {"id": row["id"], "spec": json.dumps(spec)})


def downgrade():
    with op.batch_alter_table("vodloft_playback_sessions") as batch:
        batch.drop_column("user_key")
