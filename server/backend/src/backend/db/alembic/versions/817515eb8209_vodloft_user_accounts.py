"""VODLoft 0.5.0: optional user accounts.

Revision ID: 817515eb8209
Revises: e6a2c9d4f817
Create Date: 2026-11-01

Users, their level per area of VODLoft, the Sources a limited user may use,
and the switch that turns accounts on. Operations remember who asked for
them, Stream Profiles belong to a user, and shows, movies and videos
remember who added them. Accounts start off, so an existing install keeps
working exactly as before.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "817515eb8209"
down_revision = "e6a2c9d4f817"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "username", sa.String(length=64, collation="NOCASE"), nullable=False,
            comment="Sign-in name; unique regardless of upper or lower case",
        ),
        sa.Column(
            "password_hash", sa.String(), nullable=False,
            comment="scrypt over the value the browser derives from the password",
        ),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("1"), nullable=False,
            comment="Set by an administrator's first or reset password; cleared when the user picks their own",
        ),
        sa.Column(
            "session_version", sa.Integer(), server_default="1", nullable=False,
            comment="Sessions carry this number; raising it signs the user out everywhere",
        ),
        sa.Column(
            "template_key", sa.String(), nullable=True,
            comment="The template the access list was filled in from, as long as it still matches",
        ),
        sa.Column(
            "all_sources", sa.Boolean(), server_default=sa.text("1"), nullable=False,
            comment="Off: only the Sources in user_source_access",
        ),
        sa.Column(
            "members_only", sa.Boolean(), server_default=sa.text("0"), nullable=False,
            comment="May use media that needs the install's Source memberships",
        ),
        sa.Column(
            "delete_files", sa.Boolean(), server_default=sa.text("0"), nullable=False,
            comment="May delete downloaded files from disk",
        ),
        sa.Column(
            "quick_download_preferences", sa.JSON(), nullable=True,
            comment="The user's own Quick download defaults; null: the install's defaults",
        ),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_users_created_by_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "user_access",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=32), nullable=False, comment="backend.security.access.Area"),
        sa.Column("level", sa.String(length=16), nullable=False, comment="none, view or manage"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_access_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "area", name=op.f("pk_user_access")),
    )
    op.create_table(
        "user_source_access",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_key", sa.String(length=64), nullable=False,
            comment="Id of the Source, as registered in sources",
        ),
        sa.Column(
            "domains", sa.JSON(), nullable=True,
            comment="Domains (and their subdomains) the user may use; null: all of the Source's domains",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_source_access_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "source_key", name=op.f("pk_user_source_access")),
    )
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column(
            "user_accounts_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False,
            comment="Everyone signs in with their own account instead of the one shared password",
        ))

    # Operations: who asked.
    with op.batch_alter_table("task_operations") as batch:
        batch.add_column(sa.Column(
            "requested_by_user_id", sa.Integer(), nullable=True,
            comment="The user whose request created this operation; null for VODLoft's own work or without user accounts",
        ))
        batch.create_index(batch.f("ix_task_operations_requested_by_user_id"), ["requested_by_user_id"], unique=False)
        batch.create_foreign_key(
            batch.f("fk_task_operations_requested_by_user_id_users"), "users",
            ["requested_by_user_id"], ["id"], ondelete="SET NULL",
        )

    # Ownership: Stream Profile owners, and who added shows, movies and videos.
    with op.batch_alter_table("media_items_movie") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True, comment="The user who added it; empty without user accounts"))
        batch.create_foreign_key(batch.f("fk_media_items_movie_created_by_user_id_users"), "users", ["created_by_user_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("media_items_video") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True, comment="The user who added it; empty without user accounts"))
        batch.create_foreign_key(batch.f("fk_media_items_video_created_by_user_id_users"), "users", ["created_by_user_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("shows") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True, comment="The user who added it; empty without user accounts"))
        batch.create_foreign_key(batch.f("fk_shows_created_by_user_id_users"), "users", ["created_by_user_id"], ["id"], ondelete="SET NULL")

    with op.batch_alter_table("stream_profiles") as batch:
        batch.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True, comment="The user whose feed this is; only they and those who manage every Stream Profile see it"))
        batch.create_index(batch.f("ix_stream_profiles_owner_user_id"), ["owner_user_id"], unique=False)
        batch.create_foreign_key(batch.f("fk_stream_profiles_owner_user_id_users"), "users", ["owner_user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("stream_profiles") as batch:
        batch.drop_constraint(batch.f("fk_stream_profiles_owner_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_stream_profiles_owner_user_id"))
        batch.drop_column("owner_user_id")

    with op.batch_alter_table("shows") as batch:
        batch.drop_constraint(batch.f("fk_shows_created_by_user_id_users"), type_="foreignkey")
        batch.drop_column("created_by_user_id")

    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_constraint(batch.f("fk_media_items_video_created_by_user_id_users"), type_="foreignkey")
        batch.drop_column("created_by_user_id")

    with op.batch_alter_table("media_items_movie") as batch:
        batch.drop_constraint(batch.f("fk_media_items_movie_created_by_user_id_users"), type_="foreignkey")
        batch.drop_column("created_by_user_id")

    with op.batch_alter_table("task_operations") as batch:
        batch.drop_constraint(batch.f("fk_task_operations_requested_by_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_task_operations_requested_by_user_id"))
        batch.drop_column("requested_by_user_id")

    with op.batch_alter_table("settings") as batch:
        batch.drop_column("user_accounts_enabled")
    op.drop_table("user_source_access")
    op.drop_table("user_access")
    op.drop_table("users")
