"""Keep every Download Profile in one table, whatever the show type.

Podcast and series Download Profiles each had their own table. A profile now
holds the date filters and the season filter together, and the show's episode
identification decides which apply.

Revision ID: 72dc6dfbcb05
Revises: f7b2d4e6a913
Create Date: 2026-10-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "72dc6dfbcb05"
down_revision = "f7b2d4e6a913"
branch_labels = None
depends_on = None


# Scheduler rows of a series profile used their own resource key. task_runs and
# task_schedules store the ResourceType enum name, the operation tables its value.
_ENUM_RESOURCE_TABLES = ("task_runs", "task_schedules")
_VALUE_RESOURCE_TABLES = ("task_operations", "task_operation_targets")


def upgrade() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column("download_with_countdown", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("redownload_final", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("download_days_in_past", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("download_episode_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("download_starting_from", sa.Date(), nullable=True))
        batch.add_column(sa.Column("delete_older_episodes", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("include_upcoming_seasons", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.execute("""
        UPDATE download_profiles
        SET download_with_countdown = podcast.download_with_countdown,
            redownload_final = podcast.redownload_final,
            download_days_in_past = podcast.download_days_in_past,
            download_episode_count = podcast.download_episode_count,
            download_starting_from = podcast.download_starting_from,
            delete_older_episodes = podcast.delete_older_episodes
        FROM download_profiles_podcast AS podcast
        WHERE podcast.id = download_profiles.id
    """)
    op.execute("""
        UPDATE download_profiles
        SET include_upcoming_seasons = series.include_upcoming_seasons
        FROM download_profiles_series AS series
        WHERE series.id = download_profiles.id
    """)

    op.create_table(
        "download_profile_seasons",
        sa.Column("download_profile_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["download_profile_id"], ["download_profiles.id"],
            name=op.f("fk_download_profile_seasons_download_profile_id_download_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"], ["seasons.id"],
            name=op.f("fk_download_profile_seasons_season_id_seasons"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("download_profile_id", "season_id", name=op.f("pk_download_profile_seasons")),
    )
    op.execute("""
        INSERT INTO download_profile_seasons (download_profile_id, season_id)
        SELECT DISTINCT link.download_profiles_series_id, link.season_id
        FROM download_profile_series_seasons AS link
        JOIN download_profiles ON download_profiles.id = link.download_profiles_series_id
        JOIN seasons ON seasons.id = link.season_id
    """)
    # A podcast profile downloaded every season. On a show identified by season
    # it now filters by season, so it keeps every season it has today.
    op.execute("""
        INSERT INTO download_profile_seasons (download_profile_id, season_id)
        SELECT download_profiles.id, seasons.id
        FROM download_profiles
        JOIN shows ON shows.id = download_profiles.show_id
        JOIN seasons ON seasons.show_id = shows.id
        WHERE download_profiles.type = 'podcast'
          AND shows.episode_identifier = 'seasonal'
    """)

    op.drop_table("download_profile_series_seasons")
    op.drop_table("download_profiles_series")
    op.drop_table("download_profiles_podcast")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("type")

    for table in _ENUM_RESOURCE_TABLES:
        op.execute(
            f"UPDATE {table} SET resource_type = 'DOWNLOAD_PROFILE' "
            "WHERE resource_type = 'DOWNLOAD_PROFILE_SERIES'"
        )
    for table in _VALUE_RESOURCE_TABLES:
        op.execute(
            f"UPDATE {table} SET resource_type = 'download_profile' "
            "WHERE resource_type = 'download_profile_series'"
        )


def downgrade() -> None:
    # Which table a profile goes back to follows its show's type.
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column("type", sa.String(), nullable=False, server_default="podcast"))
    op.execute("""
        UPDATE download_profiles
        SET type = 'series'
        WHERE show_id IN (SELECT id FROM shows WHERE type = 'series')
    """)

    op.create_table(
        "download_profiles_podcast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("download_with_countdown", sa.Boolean(), nullable=False),
        sa.Column("redownload_final", sa.Boolean(), nullable=False),
        sa.Column("download_days_in_past", sa.Integer(), nullable=False),
        sa.Column("download_episode_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("download_starting_from", sa.Date(), nullable=True),
        sa.Column("delete_older_episodes", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["download_profiles.id"],
            name=op.f("fk_download_profiles_podcast_id_download_profiles"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_profiles_podcast")),
    )
    op.create_table(
        "download_profiles_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("include_upcoming_seasons", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["download_profiles.id"],
            name=op.f("fk_download_profiles_series_id_download_profiles"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_download_profiles_series")),
    )
    op.create_table(
        "download_profile_series_seasons",
        sa.Column("download_profiles_series_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["season_id"], ["seasons.id"],
            name=op.f("fk_download_profile_series_seasons_season_id_seasons"),
        ),
        sa.ForeignKeyConstraint(
            ["download_profiles_series_id"], ["download_profiles_series.id"],
            name=op.f("fk_download_profile_series_seasons_series_download_profile_id_download_profiles_series"),
        ),
    )
    op.execute("""
        INSERT INTO download_profiles_podcast
            (id, download_with_countdown, redownload_final, download_days_in_past,
             download_episode_count, download_starting_from, delete_older_episodes)
        SELECT id, download_with_countdown, redownload_final, download_days_in_past,
               download_episode_count, download_starting_from, delete_older_episodes
        FROM download_profiles
        WHERE type = 'podcast'
    """)
    op.execute("""
        INSERT INTO download_profiles_series (id, include_upcoming_seasons)
        SELECT id, include_upcoming_seasons
        FROM download_profiles
        WHERE type = 'series'
    """)
    op.execute("""
        INSERT INTO download_profile_series_seasons (download_profiles_series_id, season_id)
        SELECT link.download_profile_id, link.season_id
        FROM download_profile_seasons AS link
        JOIN download_profiles_series ON download_profiles_series.id = link.download_profile_id
    """)

    op.drop_table("download_profile_seasons")
    with op.batch_alter_table("download_profiles") as batch:
        batch.alter_column("type", server_default=None)
        batch.drop_column("include_upcoming_seasons")
        batch.drop_column("delete_older_episodes")
        batch.drop_column("download_starting_from")
        batch.drop_column("download_episode_count")
        batch.drop_column("download_days_in_past")
        batch.drop_column("redownload_final")
        batch.drop_column("download_with_countdown")
