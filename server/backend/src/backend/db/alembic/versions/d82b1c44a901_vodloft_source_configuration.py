"""Store Source-declared settings and scoped secret references.

Revision ID: d82b1c44a901
Revises: c71e80b9a3f4
"""
from alembic import op
import sqlalchemy as sa

revision = "d82b1c44a901"
down_revision = "c71e80b9a3f4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.add_column(sa.Column("settings", sa.JSON, nullable=False, server_default="{}"))
        batch.add_column(sa.Column("secret_references", sa.JSON, nullable=False, server_default="{}"))
    connection = op.get_bind()
    table = sa.table("vodloft_source_connections", sa.column("id", sa.Integer),
        sa.column("secret_reference", sa.String), sa.column("secret_references", sa.JSON))
    for row in connection.execute(sa.select(table.c.id, table.c.secret_reference)).all():
        if row.secret_reference:
            connection.execute(sa.update(table).where(table.c.id == row.id).values(
                secret_references={"access_token": row.secret_reference}))
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.drop_column("secret_reference")


def downgrade():
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.add_column(sa.Column("secret_reference", sa.String, nullable=True))
    connection = op.get_bind()
    table = sa.table("vodloft_source_connections", sa.column("id", sa.Integer),
        sa.column("secret_reference", sa.String), sa.column("secret_references", sa.JSON))
    for row in connection.execute(sa.select(table.c.id, table.c.secret_references)).all():
        token = (row.secret_references or {}).get("access_token")
        if token:
            connection.execute(sa.update(table).where(table.c.id == row.id).values(
                secret_reference=token))
    with op.batch_alter_table("vodloft_source_connections") as batch:
        batch.drop_column("secret_references")
        batch.drop_column("settings")
