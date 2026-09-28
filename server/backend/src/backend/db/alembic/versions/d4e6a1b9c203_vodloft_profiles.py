"""Domain profiles, Source connections, execution specifications and placements.

Revision ID: d4e6a1b9c203
Revises: c1a8f42d6e90
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e6a1b9c203"
down_revision = "c1a8f42d6e90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("vodloft_source_domains",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("domain_id", sa.Integer, sa.ForeignKey("vodloft_domains.id"), nullable=False),
        sa.Column("support", sa.String(20), nullable=False),
        sa.UniqueConstraint("source_id", "domain_id"))
    op.create_table("vodloft_source_connections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_id", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("secret_reference", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False))
    op.create_table("local_media_profiles_domain",
        sa.Column("id", sa.Integer, sa.ForeignKey("local_media_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("domain_id", sa.Integer, sa.ForeignKey("vodloft_domains.id"), nullable=False),
        sa.Column("applicable_kinds", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"))
    with op.batch_alter_table("vodloft_source_references") as batch:
        batch.add_column(sa.Column("connection_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_vodloft_source_references_connection_id_vodloft_source_connections",
                                 "vodloft_source_connections", ["connection_id"], ["id"])
    with op.batch_alter_table("vodloft_artifacts") as batch:
        batch.drop_constraint("uq_vodloft_artifacts_item_id", type_="unique")
        batch.add_column(sa.Column("profile_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_vodloft_artifacts_profile_id_local_media_profiles",
                                 "local_media_profiles", ["profile_id"], ["id"])
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.add_column(sa.Column("profile_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("execution_spec", sa.JSON, nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
        batch.create_foreign_key("fk_vodloft_acquisition_jobs_profile_id_local_media_profiles",
                                 "local_media_profiles", ["profile_id"], ["id"])
    op.create_table("vodloft_artifact_placements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("artifact_id", sa.Integer, sa.ForeignKey("vodloft_artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("local_media_profiles.id"), nullable=False),
        sa.Column("path", sa.String, nullable=False), sa.UniqueConstraint("path"))


def downgrade():
    op.drop_table("vodloft_artifact_placements")
    with op.batch_alter_table("vodloft_acquisition_jobs") as batch:
        batch.drop_constraint("fk_vodloft_acquisition_jobs_profile_id_local_media_profiles", type_="foreignkey")
        batch.drop_column("attempts")
        batch.drop_column("execution_spec")
        batch.drop_column("profile_id")
    with op.batch_alter_table("vodloft_artifacts") as batch:
        batch.drop_constraint("fk_vodloft_artifacts_profile_id_local_media_profiles", type_="foreignkey")
        batch.drop_column("profile_id")
        batch.create_unique_constraint("uq_vodloft_artifacts_item_id", ["item_id"])
    with op.batch_alter_table("vodloft_source_references") as batch:
        batch.drop_constraint("fk_vodloft_source_references_connection_id_vodloft_source_connections", type_="foreignkey")
        batch.drop_column("connection_id")
    op.drop_table("local_media_profiles_domain")
    op.drop_table("vodloft_source_connections")
    op.drop_table("vodloft_source_domains")
