"""Upgrade the VODLoft 0.6.0 schema to 0.7.0.

Revision ID: c89f1a5ea2ba
Revises: d0f28c7f863e
Create Date: 2026-11-03

The single release migration for 0.7.0.

Download Profiles get their own Which episodes filter lines (on title, description,
duration and episode type), retention counted from the download date, downloads kept
by hand, SponsorBlock, YouTube's auto-generated subtitles and the upgrade check.
Local Media Profiles get quality goals, codecs, the audio language, subtitle
languages and the Sources they are offered for. Collections get their own yt-dlp
options, check frequency and cookies, and remember who added them. The yt-dlp
Source's own options live on settings. Messages and actions add their
destinations, rules, push devices and what was sent.

Existing data changes with it:
- The Daily Wire's episodes take their show's author as uploader.
- Existing Local Media Profiles keep downloading every subtitle language the site
  has, and a 4K profile keeps preferring H.264 but accepts VP9, AV1 and H.265.
- A Download Profile without episode types now means every type, so profiles that
  had an empty list (and downloaded nothing) are switched off instead.
- Existing installations get the default message rules, which a new installation
  gets from the initial seed.
- Imported seasons get their Source's slug back, and the duplicate seasons that
  indexing added because of the changed slug are merged into them.
"""
from __future__ import annotations

import json
import re

import sqlalchemy as sa
from alembic import op


revision = "c89f1a5ea2ba"
down_revision = "d0f28c7f863e"
branch_labels = None
depends_on = None


# What VODLoft downloaded before goals existed: H.264 when there is one, otherwise the best there is.
_COMPATIBILITY = [
    {"codec": "h264", "allowed": True}, {"codec": "av1", "allowed": False},
    {"codec": "vp9", "allowed": False}, {"codec": "h265", "allowed": False},
]
# Above 1080p there is rarely H.264, so a 4K profile took VP9 or AV1 in MP4.
_PREFER_H264 = [
    {"codec": "h264", "allowed": True}, {"codec": "vp9", "allowed": True},
    {"codec": "av1", "allowed": True}, {"codec": "h265", "allowed": True},
]

_DEFAULT_SEGMENTS = {
    "sponsor": "cut", "selfpromo": "cut", "interaction": "cut",
    "intro": "chapter", "outro": "chapter", "preview": "chapter",
    "filler": "keep", "music_offtopic": "keep",
}

# The default rules as they were in this release: problems pushed to administrators, the daily summary off.
_DEFAULT_RULES = (
    ("download_failed", "download_failed", True, "now"),
    ("sign_in_needed", "sign_in_needed", True, "now"),
    ("disk_almost_full", "disk_almost_full", True, "now"),
    ("task_failing", "task_failing", True, "now"),
    ("update_available", "update_available", True, "now"),
    ("daily_summary", "everything", False, "daily"),
)

_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<number>\d+)$")


def upgrade() -> None:
    _fill_daily_wire_uploaders()
    _download_profiles()
    _local_media_profiles()
    _collections_and_settings()
    _media_downloads()
    _messages_and_actions()
    with op.batch_alter_table("import_runs") as batch:
        batch.add_column(sa.Column(
            "download_profiles_on", sa.JSON(), nullable=False, server_default="[]",
            comment="The Download Profiles that were on in the other program, by id",
        ))
    _restore_imported_season_slugs()


# The Daily Wire's uploaders ----------------------------------------------------

def _fill_daily_wire_uploaders() -> None:
    # The Daily Wire names no uploader per episode, so new episodes take their show's author.
    op.execute(
        """
        UPDATE media_items_episode
        SET author_name = (
            SELECT NULLIF(collections.author_name, '') FROM collections
            WHERE collections.id = media_items_episode.collection_id
        )
        WHERE author_name IS NULL
          AND id IN (SELECT id FROM media_items WHERE source_key = 'dailywire')
        """
    )


# Download Profiles -------------------------------------------------------------

def _download_profiles() -> None:
    op.create_table(
        "download_profile_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "download_profile_id",
            sa.Integer(),
            sa.ForeignKey("download_profiles.id", ondelete="CASCADE", name="fk_download_profile_rules_download_profile_id_download_profiles"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, comment="Order of the line within the profile, from 0"),
        sa.Column("action", sa.String(16), nullable=False, comment="skip, only or keep"),
        sa.Column("field", sa.String(16), nullable=False, comment="title, description or duration"),
        sa.Column("pattern", sa.String(), nullable=True, comment="The regular expression of a title or description rule"),
        sa.Column("ignore_case", sa.Boolean(), nullable=False),
        sa.Column("duration_operator", sa.String(16), nullable=True, comment="shorter or longer, for a duration rule"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("episode_types", sa.JSON(), nullable=True, comment="The episode type keys of a types rule"),
    )
    op.create_index("ix_download_profile_rules_download_profile_id", "download_profile_rules", ["download_profile_id"])

    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "retention_from", sa.String(16), nullable=False, server_default="published",
            comment="Whether a date window deletes episodes N days after publication or after downloading",
        ))
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), server_default="fallback", nullable=False,
            comment="YouTube's auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))
        # Existing profiles keep downloading the whole video until SponsorBlock is switched on.
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), server_default="0", nullable=False))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), server_default=json.dumps(_DEFAULT_SEGMENTS), nullable=False,
            comment="SponsorBlock segment type to keep, chapter or cut, for YouTube Collections",
        ))
        # Existing profiles start with the upgrade check off; new ones start with it on.
        batch.add_column(sa.Column("upgrade_check", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column(
            "upgrade_after_days", sa.Integer(), nullable=False, server_default="7",
            comment="Days after downloading that the upgrade check first looks",
        ))
        batch.add_column(sa.Column(
            "upgrade_repeat", sa.String(16), nullable=False, server_default="once",
            comment="once, twice (again after 30 days) or every (up to 3 times)",
        ))
        batch.add_column(sa.Column(
            "upgrade_improvements", sa.JSON(), nullable=False, server_default='["resolution", "sponsorblock"]',
            comment="What counts as a better version: resolution, sponsorblock, subtitles or codec",
        ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.alter_column("sponsorblock_segments", server_default=None)

    with op.batch_alter_table("media_downloads_episode") as batch:
        batch.add_column(sa.Column(
            "kept", sa.Boolean(), nullable=False, server_default="0",
            comment="Kept by hand: retention never deletes this download",
        ))
        batch.add_column(sa.Column(
            "upgrade_checks", sa.Integer(), nullable=False, server_default="0",
            comment="How many times the upgrade check has looked at this download",
        ))
        batch.add_column(sa.Column(
            "upgrade_check_at", sa.DateTime(), nullable=True, comment="When the upgrade check looks next; empty when it will not",
        ))
        batch.add_column(sa.Column(
            "upgrade_result", sa.String(16), nullable=True, comment="What the last upgrade check found: upgraded or checked",
        ))

    # Before, a Download Profile with an empty episode type list downloaded nothing. Without
    # episode types it now downloads every type, so those profiles stop downloading
    # automatically instead of starting to download everything.
    op.execute(sa.text(
        "UPDATE download_profiles SET enable_profile = 0 "
        "WHERE ep_id_type_list IS NULL OR json_array_length(ep_id_type_list) = 0"
    ))


# Local Media Profiles ----------------------------------------------------------

def _local_media_profiles() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column("subtitle_languages", sa.JSON(), server_default='["en"]', nullable=False))
        batch.add_column(sa.Column("subtitle_language_mode", sa.String(16), server_default="listed", nullable=False))
        batch.add_column(sa.Column("quality_goal", sa.String(16), server_default="compatibility", nullable=False))
        batch.add_column(sa.Column("video_codecs", sa.JSON(), server_default=json.dumps(_COMPATIBILITY), nullable=False))
        batch.add_column(sa.Column("codec_fallback", sa.String(8), server_default="best", nullable=False))
        batch.add_column(sa.Column("container", sa.String(8), server_default="mp4", nullable=False))
        batch.add_column(sa.Column("audio_codec", sa.String(8), server_default="aac", nullable=False))
        batch.add_column(sa.Column("audio_format", sa.String(8), server_default="m4a", nullable=False))
        batch.add_column(sa.Column("audio_language", sa.String(16), nullable=True))
        batch.add_column(sa.Column(
            "source_keys", sa.JSON(), nullable=True,
            comment="The Sources this profile is offered for; NULL offers it for every Source",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.alter_column("video_codecs", server_default=None)
    profiles = sa.table(
        "local_media_profiles",
        sa.column("preferred_format", sa.String()), sa.column("subtitle_language_mode", sa.String()),
        sa.column("quality_goal", sa.String()), sa.column("video_codecs", sa.JSON()),
    )
    # Existing profiles keep downloading every subtitle language the site has.
    op.execute(profiles.update().values(subtitle_language_mode="site"))
    op.execute(
        profiles.update().where(profiles.c.preferred_format == "format_4k")
        .values(quality_goal="custom", video_codecs=_PREFER_H264)
    )


# Collections and the yt-dlp Source ---------------------------------------------

def _collections_and_settings() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options for this Collection, added after the Local Media Profile's",
        ))
        batch.add_column(sa.Column(
            "added_by_id", sa.Integer(), nullable=True, comment="Who added the Collection, for their own notifications",
        ))
        batch.create_foreign_key("fk_collections_added_by_id_users", "users", ["added_by_id"], ["id"], ondelete="SET NULL")
        batch.add_column(sa.Column(
            "cookies_mode", sa.String(), nullable=False, server_default="automatic",
            comment="When downloads use the Source's cookies file: automatic, never or always",
        ))
        batch.add_column(sa.Column(
            "cookies_needed_until", sa.DateTime(), nullable=True,
            comment="Automatic cookies: downloads use the cookies file until then",
        ))
        batch.add_column(sa.Column(
            "check_frequency", sa.String(), nullable=False, server_default="default",
            comment="How often VODLoft looks for new episodes: default, less_often or own",
        ))
        batch.add_column(sa.Column(
            "check_cron", sa.String(), nullable=True, comment="The Collection's own schedule, with check_frequency own",
        ))
    with op.batch_alter_table("settings") as batch:
        batch.add_column(sa.Column(
            "ytdlp_options", sa.Text(), server_default="", nullable=False,
            comment="Your own yt-dlp options for every download of the yt-dlp Source, one or more per line",
        ))


# What a download kept ----------------------------------------------------------

def _media_downloads() -> None:
    with op.batch_alter_table("media_downloads") as batch:
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=True,
            comment="The SponsorBlock segments of the video as published, and whether each became a chapter or was cut",
        ))
        batch.add_column(sa.Column("video_height", sa.Integer(), nullable=True, comment="The smaller side of the kept video stream, in pixels"))
        batch.add_column(sa.Column("video_codec", sa.String(20), nullable=True, comment="The codec of the kept video stream"))
        batch.add_column(sa.Column(
            "subtitle_languages", sa.JSON(), nullable=True, comment="The languages of the site's own subtitles the download kept",
        ))


# Messages and actions ----------------------------------------------------------

def _messages_and_actions() -> None:
    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False, comment="apprise, jellyfin, emby, plex, webhook or script"),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("service", sa.String(64), nullable=False, comment="The Apprise service key, or the kind"),
        sa.Column("encrypted_config", sa.Text(), nullable=False, comment="The destination's settings as encrypted JSON"),
        sa.Column("masked", sa.String(255), nullable=False, comment="The destination, safe to show"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Whose own rule this is; empty for a rule on Settings",
        ),
        sa.Column("personal", sa.Boolean(), nullable=False, comment="A person's own rule, from Account › Notifications"),
        sa.Column("default_key", sa.String(32), nullable=True, comment="Which default rule this is, if any"),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("collection_scope", sa.String(16), nullable=False, comment="any, chosen or added (by this person)"),
        sa.Column("collection_ids", sa.JSON(), nullable=False),
        sa.Column("push", sa.Boolean(), nullable=False, comment="Push to administrators, or to the person of a personal rule"),
        sa.Column("destination_ids", sa.JSON(), nullable=False),
        sa.Column("delivery", sa.String(16), nullable=False, comment="now, grouped (per Collection) or daily"),
        sa.Column("summary_time", sa.String(5), nullable=False, comment="When a daily summary goes out"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_rules_user_id", "notification_rules", ["user_id"])
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
            comment="The person it is about, such as who asked for a Quick download",
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(512), nullable=True, comment="The page in VODLoft it is about"),
        sa.Column("data", sa.JSON(), nullable=False, comment="Details for actions, such as the file's folder"),
        sa.Column("dedupe_key", sa.String(255), nullable=True, comment="The same problem is sent again only after a day"),
    )
    op.create_index("ix_notification_events_event", "notification_events", ["event"])
    op.create_index("ix_notification_events_dedupe", "notification_events", ["dedupe_key", "occurred_at"])
    op.create_table(
        "push_vapid_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_private_key", sa.Text(), nullable=False),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Whose device it is; empty when VODLoft has no user accounts",
        ),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_subscription", sa.Text(), nullable=False),
        sa.Column("device_name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("notification_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "destination_id", sa.Integer(), sa.ForeignKey("notification_destinations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id", sa.Integer(), sa.ForeignKey("push_subscriptions.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
            comment="Who a push went to",
        ),
        sa.Column("group_key", sa.String(128), nullable=True, comment="Deliveries with the same key go out as one message"),
        sa.Column("status", sa.String(16), nullable=False, comment="PENDING, SENT, FAILED or CANCELED"),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_deliveries_event_id", "notification_deliveries", ["event_id"])
    op.create_index("ix_notification_deliveries_user_id", "notification_deliveries", ["user_id"])
    op.create_index("ix_notification_deliveries_pending", "notification_deliveries", ["status", "next_attempt_at"])

    rules = sa.table(
        "notification_rules",
        sa.column("position", sa.Integer), sa.column("personal", sa.Boolean), sa.column("default_key", sa.String),
        sa.column("enabled", sa.Boolean), sa.column("event", sa.String), sa.column("collection_scope", sa.String),
        sa.column("collection_ids", sa.JSON), sa.column("push", sa.Boolean), sa.column("destination_ids", sa.JSON),
        sa.column("delivery", sa.String), sa.column("summary_time", sa.String),
    )
    op.bulk_insert(rules, [
        {
            "position": position, "personal": False, "default_key": key, "enabled": enabled, "event": event,
            "collection_scope": "any", "collection_ids": [], "push": True, "destination_ids": [], "delivery": delivery,
            "summary_time": "08:00",
        }
        for position, (key, event, enabled, delivery) in enumerate(_DEFAULT_RULES, start=1)
    ])


# Imported season slugs ---------------------------------------------------------

def _restore_imported_season_slugs() -> None:
    """Give imported seasons back their Source's slug, and merge the duplicate seasons that caused.

    An import used to make every season slug unique across all of VODLoft, while a season
    slug only has to be unique within its collection. The second imported show with an
    "extras" season got "extras-2", the next "extras-3", and so on. Indexing finds a
    collection's seasons by the Source's slug, so it did not recognise these seasons and
    added the same season a second time.

    A season is restored when the import created it, its slug ends in "-<n>" with n of 2 or
    more, and either indexing already added a season of the same name under the plain slug,
    or every slug the import would have tried before it (the plain slug, then "-2" up to
    "-<n-1>") belongs to a season of another collection. A duplicate's episodes and Download
    Profile choices move to the imported season and the duplicate is removed.
    """
    bind = op.get_bind()
    seasons = bind.execute(sa.text("SELECT id, collection_id, slug, name FROM seasons")).all()
    imported = set(bind.execute(sa.text(
        "SELECT entity_id FROM import_links WHERE kind = 'season' AND entity_id IS NOT NULL"
    )).scalars())
    collections_by_slug: dict[str, set[int]] = {}
    for _id, collection_id, slug, _name in seasons:
        collections_by_slug.setdefault(slug, set()).add(collection_id)

    for season_id, collection_id, slug, name in seasons:
        match = _SUFFIX.match(slug)
        if season_id not in imported or match is None or int(match["number"]) < 2:
            continue
        base = match["base"]
        duplicate = bind.execute(
            sa.text("SELECT id, name FROM seasons WHERE collection_id = :collection AND slug = :slug"),
            {"collection": collection_id, "slug": base},
        ).one_or_none()
        if duplicate is not None:
            if duplicate.name != name:
                continue
            _merge(bind, keep=season_id, remove=duplicate.id)
        else:
            tried = [base] + [f"{base}-{number}" for number in range(2, int(match["number"]))]
            if not all(collections_by_slug.get(candidate, set()) - {collection_id} for candidate in tried):
                continue
        bind.execute(sa.text("UPDATE seasons SET slug = :slug WHERE id = :id"), {"slug": base, "id": season_id})


def _merge(bind, *, keep: int, remove: int) -> None:
    ids = {"keep": keep, "remove": remove}
    bind.execute(sa.text("UPDATE media_items_episode SET season_id = :keep WHERE season_id = :remove"), ids)
    bind.execute(sa.text(
        "INSERT INTO download_profile_seasons (download_profile_id, season_id) "
        "SELECT download_profile_id, :keep FROM download_profile_seasons WHERE season_id = :remove "
        "AND download_profile_id NOT IN (SELECT download_profile_id FROM download_profile_seasons WHERE season_id = :keep)"
    ), ids)
    bind.execute(sa.text("DELETE FROM download_profile_seasons WHERE season_id = :remove"), ids)
    bind.execute(sa.text("DELETE FROM seasons WHERE id = :remove"), ids)


def downgrade() -> None:
    # The suffixed season slugs were a mistake, and the other data changes have nothing to restore.
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_column("download_profiles_on")

    with op.batch_alter_table("collections") as batch:
        batch.drop_constraint("fk_collections_added_by_id_users", type_="foreignkey")
        for column in ("check_cron", "check_frequency", "cookies_needed_until", "cookies_mode", "added_by_id", "ytdlp_options"):
            batch.drop_column(column)
    op.drop_table("notification_deliveries")
    op.drop_table("push_subscriptions")
    op.drop_table("push_vapid_keys")
    op.drop_table("notification_events")
    op.drop_table("notification_rules")
    op.drop_table("notification_destinations")

    with op.batch_alter_table("settings") as batch:
        batch.drop_column("ytdlp_options")
    with op.batch_alter_table("media_downloads") as batch:
        for column in ("subtitle_languages", "video_codec", "video_height", "sponsorblock_segments"):
            batch.drop_column(column)
    with op.batch_alter_table("local_media_profiles") as batch:
        for column in (
            "source_keys", "audio_language", "audio_format", "audio_codec", "container", "codec_fallback",
            "video_codecs", "quality_goal", "subtitle_language_mode", "subtitle_languages",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("media_downloads_episode") as batch:
        for column in ("upgrade_result", "upgrade_check_at", "upgrade_checks", "kept"):
            batch.drop_column(column)
    with op.batch_alter_table("download_profiles") as batch:
        for column in (
            "upgrade_improvements", "upgrade_repeat", "upgrade_after_days", "upgrade_check",
            "sponsorblock_segments", "sponsorblock_enabled", "auto_subtitles", "retention_from",
        ):
            batch.drop_column(column)
    op.drop_index("ix_download_profile_rules_download_profile_id", table_name="download_profile_rules")
    op.drop_table("download_profile_rules")
