"""Upgrade the VODLoft 0.8.0 schema to 0.9.0.

Revision ID: 2f7a91c4d8e3
Revises: bb0e7c5e17cc
Create Date: 2026-11-17

The single release migration for 0.9.0. It runs the steps of the migrations it replaces in their
order; each step's docstring says what it does.

The settings every stream profile type shares (how many episodes it offers, live episodes and
passing the Site's stream on through VODLoft) move from the RSS table to stream_profiles. IPTV and
WebDAV stream profiles get their own tables, and every user and the install get a secret token for
their playlist and guide. Local Media Profiles get their own filename mode, file dates and NFO
options, Collections a genre and content rating for NFO files, and Sites remember until when their
automatic downloads wait after a throttled download.

Existing data changes with it: every RSS feed keeps its shared settings, existing profiles keep the
filename mode in Settings, and existing users get a stream token of their own.
"""
from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op


revision = "2f7a91c4d8e3"
down_revision = "bb0e7c5e17cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _upgrade_stream_settings_on_every_stream_profile()
    _upgrade_iptv_stream_profiles()
    _upgrade_iptv_catch_up()
    _upgrade_media_server_options()
    _upgrade_webdav_stream_profiles()
    _upgrade_collection_genre_and_content_rating()
    _upgrade_site_downloads_paused_until()


def downgrade() -> None:
    _downgrade_site_downloads_paused_until()
    _downgrade_collection_genre_and_content_rating()
    _downgrade_webdav_stream_profiles()
    _downgrade_media_server_options()
    _downgrade_iptv_catch_up()
    _downgrade_iptv_stream_profiles()
    _downgrade_stream_settings_on_every_stream_profile()


# --- stream settings on every stream profile (was 555cdd9ad18a) ---

_SHARED_STREAM_SETTINGS = ("max_items", "stream_live_episodes", "proxy_source_stream", "live_episode_handoff_ids")


def _shared_stream_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "max_items", sa.Integer(), nullable=False, server_default="0",
            comment="The most episodes offered, newest first; 0 offers every one",
        ),
        sa.Column("stream_live_episodes", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "proxy_source_stream", sa.Boolean(), nullable=False, server_default="1",
            comment="Pass the Site's stream on through VODLoft instead of sending apps to the Site",
        ),
        sa.Column("live_episode_handoff_ids", sa.JSON(), nullable=False, server_default="[]"),
    ]


def _copy_shared_stream_settings(source: str, target: str) -> None:
    """Copy the shared values of every RSS feed from one table to the other, by its id."""
    assignments = ", ".join(
        f"{column} = (SELECT {source}.{column} FROM {source} WHERE {source}.id = {target}.id)"
        for column in _SHARED_STREAM_SETTINGS
    )
    op.execute(sa.text(f"UPDATE {target} SET {assignments} WHERE id IN (SELECT id FROM {source})"))


def _upgrade_stream_settings_on_every_stream_profile() -> None:
    """Move the settings every stream profile type shares from the RSS table to stream_profiles."""
    with op.batch_alter_table("stream_profiles") as batch:
        for column in _shared_stream_columns():
            batch.add_column(column)
    _copy_shared_stream_settings("stream_profiles_rss", "stream_profiles")
    with op.batch_alter_table("stream_profiles_rss") as batch:
        for column in _SHARED_STREAM_SETTINGS:
            batch.drop_column(column)


def _downgrade_stream_settings_on_every_stream_profile() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        for column in _shared_stream_columns():
            batch.add_column(column)
    _copy_shared_stream_settings("stream_profiles", "stream_profiles_rss")
    with op.batch_alter_table("stream_profiles") as batch:
        for column in _SHARED_STREAM_SETTINGS:
            batch.drop_column(column)


# --- iptv stream profiles (was a323216be495) ---

def _give_each_row_a_token(table: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id FROM {table}")).scalars().all()
    for row_id in rows:
        bind.execute(
            sa.text(f"UPDATE {table} SET stream_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(24), "id": row_id},
        )


def _upgrade_iptv_stream_profiles() -> None:
    """Add IPTV stream profiles, and the stream tokens of the playlist and guide with every channel."""
    op.create_table(
        "stream_profiles_iptv",
        sa.Column("id", sa.Integer(), sa.ForeignKey("stream_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_number", sa.Integer(), nullable=False, comment="Where the channel sits in an app's channel list"),
        sa.Column(
            "channel_group", sa.String(), nullable=True,
            comment="The group an app lists the channel under; empty uses the collection's Site name",
        ),
    )

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "stream_token", sa.String(), nullable=True,
            comment="Secret in the addresses of the user's own playlist and guide, with all their channels",
        ))
    _give_each_row_a_token("users")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("stream_token", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_users_stream_token", ["stream_token"])

    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column(
            "stream_token", sa.String(64), nullable=True,
            comment="Secret in the addresses of the playlist and guide with every channel, for an install without user accounts",
        ))
    _give_each_row_a_token("settings")
    with op.batch_alter_table("settings") as batch:
        batch.alter_column("stream_token", existing_type=sa.String(64), nullable=False)


def _downgrade_iptv_stream_profiles() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("stream_token")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_stream_token", type_="unique")
        batch.drop_column("stream_token")
    op.drop_table("stream_profiles_iptv")


# --- iptv catch up (was affb021acdf2) ---

def _upgrade_iptv_catch_up() -> None:
    """Add what an IPTV channel shows between live episodes, its catch-up window and its episode playlist."""
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        batch.add_column(sa.Column(
            "between_live_episodes", sa.String(32), nullable=False, server_default="newest_episode",
            comment="What the channel shows while none of its episodes is live: an IptvBetweenLiveEpisodes value",
        ))
        batch.add_column(sa.Column(
            "catch_up_days", sa.Integer(), nullable=False, server_default="7",
            comment="How many days back the guide reaches, and apps can play an episode again from it",
        ))
        batch.add_column(sa.Column(
            "list_episodes", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Whether the channel's episodes are also listed on their own, in the episode playlist",
        ))
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        for column in ("between_live_episodes", "catch_up_days", "list_episodes"):
            batch.alter_column(column, server_default=None)


def _downgrade_iptv_catch_up() -> None:
    with op.batch_alter_table("stream_profiles_iptv") as batch:
        batch.drop_column("list_episodes")
        batch.drop_column("catch_up_days")
        batch.drop_column("between_live_episodes")


# --- media server options (was ee6dab087875) ---

def _upgrade_media_server_options() -> None:
    """Give Local Media Profiles their own filename mode, file dates and NFO options."""
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "kodi_safe_nfo", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="NFO files replace the characters Kodi cannot show, such as emoji",
        ))
        batch.add_column(sa.Column(
            "filename_restriction_mode", sa.String(16), nullable=False, server_default="system",
            comment="How file and folder names are made safe: unrestricted, windows or restricted (ASCII only)",
        ))
        batch.add_column(sa.Column(
            "file_date_from_publish_date", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Downloaded files get the date the media was published, so players sort them by air date",
        ))
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.add_column(sa.Column(
            "show_nfo", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Write tvshow.nfo in the collection's folder and season.nfo in each season's folder",
        ))


def _downgrade_media_server_options() -> None:
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.drop_column("show_nfo")
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("file_date_from_publish_date")
        batch.drop_column("filename_restriction_mode")
        batch.drop_column("kodi_safe_nfo")


# --- webdav stream profiles (was b54038f5c9f6) ---

def _upgrade_webdav_stream_profiles() -> None:
    """Add WebDAV stream profiles: a read-only network folder laid out as a TV show."""
    op.create_table(
        "stream_profiles_webdav",
        sa.Column("id", sa.Integer(), sa.ForeignKey("stream_profiles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("folder_name", sa.String(), nullable=True, comment="The show's folder; empty uses the profile's title"),
        sa.Column(
            "season_folders", sa.String(16), nullable=False,
            comment="How the episodes are sorted into folders: a WebdavSeasonFolders value",
        ),
        sa.Column(
            "metadata_files", sa.String(32), nullable=False,
            comment="What is listed beside the episodes for media players: a WebdavMetadataFiles value",
        ),
    )


def _downgrade_webdav_stream_profiles() -> None:
    op.drop_table("stream_profiles_webdav")


# --- collection genre and content rating (was 6cc8e0f91b00) ---

def _upgrade_collection_genre_and_content_rating() -> None:
    """Add a genre and a content rating to Collections, for the NFO files media servers read."""
    op.add_column("collections", sa.Column("genre", sa.String(), nullable=True, comment="The show's genre in its NFO files"))
    op.add_column("collections", sa.Column(
        "content_rating", sa.String(), nullable=True, comment="The show's content rating in its NFO files, such as TV-14",
    ))


def _downgrade_collection_genre_and_content_rating() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("content_rating")
        batch.drop_column("genre")


# --- site downloads paused until (was 2f7a91c4d8e3) ---

def _upgrade_site_downloads_paused_until() -> None:
    """Remember until when a Site's automatic downloads wait after it throttled a download."""
    op.add_column("sites", sa.Column(
        "downloads_paused_until", sa.DateTime(timezone=True), nullable=True,
        comment="Automatic downloads from the Site wait until then, because it throttled a download",
    ))


def _downgrade_site_downloads_paused_until() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("downloads_paused_until")
