"""Upgrade the VODLoft 0.7.0 schema to 0.8.0.

Revision ID: d7e173de7e72
Revises: c89f1a5ea2ba
Create Date: 2026-11-12

The single release migration for 0.8.0. It runs the steps of the migrations it replaces in their
order; each step's docstring says what it does.

Collections and videos get the Site they are on, and a Site table replaces the domain preferences.
Which episodes becomes one ordered list of filters, with one Download Profile per Collection and
Local Media Profile. Local Media Profiles are offered per Site and keep auto-generated subtitles
and SponsorBlock. Media items say which access they need for locked media, episodes and videos
remember when they were last looked up, downloads keep their length, and Collections choose their
episode order and remember how often they are opened.

Existing data changes with it:
- Stored publish statuses get the names every Source shares, and "cancelled" history actions are
  spelled "canceled".
- Duplicate Download Profiles of one Collection and Local Media Profile are merged or removed
  (logged), and Daily Wire-only Local Media Profiles move to 480p, 720p or 1080p, merging into an
  identical profile where there is one.
- YouTube feeds that stream move to 720p or 1080p and proxy through VODLoft; feeds of Sites without
  HLS video move to MP4.
- Daily Wire Download Profiles get the upgrade check for a different length, imported files join
  their Collection's Download Profile, and existing Download Profiles keep SponsorBlock's new
  highlight, hook and viewer chapter types as before.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date

import sqlalchemy as sa
from alembic import op


revision = "d7e173de7e72"
down_revision = "c89f1a5ea2ba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _upgrade_canceled_spelling()
    _upgrade_sites()
    _upgrade_video_refresh_state()
    _upgrade_neutral_publish_statuses()
    _upgrade_every_season()
    _upgrade_which_episodes_filters()
    _upgrade_source_stream_column()
    _upgrade_daily_wire_resolutions()
    _upgrade_youtube_stream_resolutions()
    _upgrade_hls_feeds_need_hls_video()
    _upgrade_length_upgrade_checks()
    _upgrade_proxy_by_default()
    _upgrade_episode_order()
    _upgrade_drop_append_media_type()
    _upgrade_picture_comments()
    _upgrade_profile_lookup_indexes()
    _upgrade_imported_downloads_join_profiles()
    _upgrade_locked_media()
    _upgrade_more_sponsorblock_types()
    _upgrade_library_sort()
    _upgrade_metadata_refreshed_at()
    _upgrade_local_media_profile_sites()
    _upgrade_settings_on_local_media_profiles()


def downgrade() -> None:
    _downgrade_settings_on_local_media_profiles()
    _downgrade_local_media_profile_sites()
    _downgrade_metadata_refreshed_at()
    _downgrade_library_sort()
    _downgrade_more_sponsorblock_types()
    _downgrade_locked_media()
    _downgrade_imported_downloads_join_profiles()
    _downgrade_profile_lookup_indexes()
    _downgrade_picture_comments()
    _downgrade_drop_append_media_type()
    _downgrade_episode_order()
    _downgrade_proxy_by_default()
    _downgrade_length_upgrade_checks()
    _downgrade_hls_feeds_need_hls_video()
    _downgrade_youtube_stream_resolutions()
    _downgrade_daily_wire_resolutions()
    _downgrade_source_stream_column()
    _downgrade_which_episodes_filters()
    _downgrade_every_season()
    _downgrade_neutral_publish_statuses()
    _downgrade_video_refresh_state()
    _downgrade_sites()
    _downgrade_canceled_spelling()


# --- canceled spelling (was 7b3e9d2a4c61) ---

def _upgrade_canceled_spelling() -> None:
    """Spell canceled download history actions the way the rest of VODLoft does."""
    op.execute("UPDATE media_download_history SET action = 'canceled' WHERE action = 'cancelled'")


def _downgrade_canceled_spelling() -> None:
    op.execute("UPDATE media_download_history SET action = 'cancelled' WHERE action = 'canceled'")


# --- sites (was 2bd0eb5fe4a6) ---

# The Sites of the Sources made for one site, and the domains they had preferences on.
_NAMED_SITES = {
    "dailywire": ("The Daily Wire", "dailywire.com"),
    "npo": ("NPO Start", "npo.nl"),
}


def _upgrade_sites() -> None:
    """Sites: the website a collection or video is on, whichever Source fetches it."""
    sites = op.create_table(
        "sites",
        sa.Column("key", sa.String(), nullable=False, comment="The Site's key, as the sources package tells it"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False, comment="The domains of the Site VODLoft has seen"),
        sa.Column(
            "preferred_source_key", sa.String(), nullable=True,
            comment="The Source asked first for links on this Site, when several Sources handle it",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_sites")),
    )
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "site_key", sa.String(), nullable=True,
            comment="The Site the collection is on; filled in the background for older collections",
        ))
        batch.add_column(sa.Column("site_ref", sa.String(), nullable=True, comment="The Site's own id for the collection"))
        batch.create_foreign_key("fk_collections_site_key_sites", "sites", ["site_key"], ["key"])
        batch.create_index("ix_collections_site_key", ["site_key"])
        batch.create_unique_constraint("uq_collections_site_key", ["site_key", "site_ref"])
    with op.batch_alter_table("media_items_video") as batch:
        batch.add_column(sa.Column(
            "site_key", sa.String(), nullable=True,
            comment="The Site the video is on; filled in the background for older videos",
        ))
        batch.create_foreign_key("fk_media_items_video_site_key_sites", "sites", ["site_key"], ["key"])
        batch.create_index("ix_media_items_video_site_key", ["site_key"])

    connection = op.get_bind()
    preferences = dict(connection.execute(sa.text("SELECT domain, source_key FROM source_domain_preferences")).all())
    rows = []
    for key, (name, domain) in _NAMED_SITES.items():
        used = connection.execute(sa.text(
            "SELECT 1 FROM collections WHERE source_key = :key "
            "UNION SELECT 1 FROM media_items WHERE source_key = :key AND type = 'video'"
        ), {"key": key}).first()
        if used is not None or domain in preferences:
            rows.append({"key": key, "name": name, "domains": [domain], "preferred_source_key": preferences.get(domain)})
    if rows:
        op.bulk_insert(sites, rows)
    for row in rows:
        connection.execute(
            sa.text("UPDATE collections SET site_key = :key, site_ref = slug WHERE source_key = :key"),
            {"key": row["key"]},
        )
        connection.execute(
            sa.text(
                "UPDATE media_items_video SET site_key = :key WHERE id IN "
                "(SELECT id FROM media_items WHERE source_key = :key AND type = 'video')"
            ),
            {"key": row["key"]},
        )
    op.drop_table("source_domain_preferences")


def _downgrade_sites() -> None:
    op.create_table(
        "source_domain_preferences",
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("domain", name=op.f("pk_source_domain_preferences")),
    )
    connection = op.get_bind()
    for key, (_name, domain) in _NAMED_SITES.items():
        connection.execute(
            sa.text(
                "INSERT INTO source_domain_preferences (domain, source_key) "
                "SELECT :domain, preferred_source_key FROM sites WHERE key = :key AND preferred_source_key IS NOT NULL"
            ),
            {"key": key, "domain": domain},
        )
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_index("ix_media_items_video_site_key")
        batch.drop_constraint("fk_media_items_video_site_key_sites", type_="foreignkey")
        batch.drop_column("site_key")
    with op.batch_alter_table("collections") as batch:
        batch.drop_constraint("uq_collections_site_key", type_="unique")
        batch.drop_index("ix_collections_site_key")
        batch.drop_constraint("fk_collections_site_key_sites", type_="foreignkey")
        batch.drop_column("site_ref")
        batch.drop_column("site_key")
    op.drop_table("sites")


# --- video refresh state (was part of 5b75b63e55f2) ---

def _upgrade_video_refresh_state() -> None:
    """Single videos are looked up again after publication until their metadata is final."""
    with op.batch_alter_table("media_items_video") as batch:
        batch.add_column(sa.Column(
            "metadata_is_final", sa.Boolean(), nullable=False, server_default="1",
            comment="False while VODLoft still looks the video up again after publication",
        ))


def _downgrade_video_refresh_state() -> None:
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_column("metadata_is_final")


# --- neutral publish statuses (was b9dbb772c34e) ---

_RENAMED = {"dw_processing": "source_processing", "published_with_countdown": "published_preliminary"}


_METADATA_KEYS = {"ep_status.dw_processing.slug": "ep_status.source_processing.slug"}


# JSON columns, and the keys in them that hold a publish status.
_JSON_FIELDS = (
    ("media_download_history", "metadata", "started_publish_status"),
    ("task_operations", "context", "episode_publish_status"),
    ("task_operations", "result", "publish_status"),
)


def _rename_values(connection, renames: dict[str, str]) -> None:
    for old, new in renames.items():
        connection.execute(sa.text(
            "UPDATE media_items_episode SET publish_status = :new WHERE publish_status = :old"
        ), {"old": old, "new": new})
        connection.execute(sa.text(
            "UPDATE media_downloads_episode SET downloaded_publish_status = :new WHERE downloaded_publish_status = :old"
        ), {"old": old, "new": new})
    for table, column, key in _JSON_FIELDS:
        rows = connection.execute(sa.text(
            f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"
        )).all()
        for row_id, raw in rows:
            value = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(value, dict) and value.get(key) in renames:
                value[key] = renames[value[key]]
                connection.execute(sa.text(
                    f"UPDATE {table} SET {column} = :value WHERE id = :id"
                ), {"value": json.dumps(value), "id": row_id})


def _rename_keys(connection, renames: dict[str, str]) -> None:
    for old, new in renames.items():
        connection.execute(sa.text("UPDATE metadata SET key = :new WHERE key = :old"), {"old": old, "new": new})


def _upgrade_neutral_publish_statuses() -> None:
    """Publish statuses every Source shares: dw_processing and published_with_countdown get neutral names."""
    connection = op.get_bind()
    _rename_values(connection, _RENAMED)
    _rename_keys(connection, _METADATA_KEYS)


def _downgrade_neutral_publish_statuses() -> None:
    connection = op.get_bind()
    _rename_values(connection, {new: old for old, new in _RENAMED.items()})
    _rename_keys(connection, {new: old for old, new in _METADATA_KEYS.items()})


# --- every season (was ce5df2342e6f) ---

def _upgrade_every_season() -> None:
    """Let a Download Profile download every season, without a seasons line, and filter on seasons in its own lines."""
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "all_seasons", sa.Boolean(), server_default="0", nullable=False,
            comment="The seasons line was removed: every season downloads, upcoming ones included",
        ))
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.add_column(sa.Column("season_slugs", sa.JSON(), nullable=True, comment="The season slugs of a seasons rule"))


def _downgrade_every_season() -> None:
    op.execute("DELETE FROM download_profile_rules WHERE field = 'seasons'")
    with op.batch_alter_table("download_profile_rules") as batch:
        batch.drop_column("season_slugs")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("all_seasons")


# --- which episodes filters (was cbad9977fd7b) ---

logger = logging.getLogger("alembic.runtime.migration")


_FILTER_COLUMNS = (
    "download_profile_id", "position", "action", "field", "pattern", "duration_operator", "duration_seconds",
    "episode_types", "season_slugs", "include_upcoming", "days", "count", "starting_from",
)


# What two profiles must share, besides their episode types, to become one profile.
_PROFILE_SETTINGS = (
    "download_with_countdown", "redownload_final", "delete_older_episodes", "auto_subtitles", "sponsorblock_enabled",
    "sponsorblock_segments", "upgrade_check", "upgrade_after_days", "upgrade_repeat", "upgrade_improvements",
)


def _json_which_episodes_filters(value):
    return json.loads(value) if isinstance(value, str) else value


def _filter(profile_id: int, action: str, field: str, **settings) -> dict:
    return {
        "download_profile_id": profile_id, "position": 0, "action": action, "field": field,
        "pattern": None, "duration_operator": None, "duration_seconds": None, "episode_types": None,
        "season_slugs": None, "include_upcoming": False, "days": None, "count": None, "starting_from": None,
        **settings,
    }


def _date_line(profile) -> dict | None:
    if profile.download_episode_count and profile.download_episode_count > 0:
        return _filter(profile.id, "only", "published", count=profile.download_episode_count)
    if profile.download_days_in_past and profile.download_days_in_past > 0:
        field = "downloaded" if profile.retention_from == "downloaded" else "published"
        return _filter(profile.id, "only", field, days=profile.download_days_in_past)
    if profile.download_starting_from is not None:
        # SQLite hands the stored day back as text, and the Date column only takes a date.
        return _filter(
            profile.id, "only", "published", starting_from=date.fromisoformat(str(profile.download_starting_from)[:10]),
        )
    return None


def _filters_of(bind, profile, seasonal: bool) -> list[dict]:
    filters: list[dict] = []
    if seasonal and not profile.all_seasons:
        slugs = list(bind.execute(sa.text(
            "SELECT seasons.slug FROM download_profile_seasons "
            "JOIN seasons ON seasons.id = download_profile_seasons.season_id "
            "WHERE download_profile_seasons.download_profile_id = :id ORDER BY seasons.\"index\""
        ), {"id": profile.id}).scalars())
        filters.append(_filter(
            profile.id, "only", "seasons", season_slugs=slugs, include_upcoming=bool(profile.include_upcoming_seasons),
        ))
    types = _json_which_episodes_filters(profile.ep_id_type_list) or []
    if types:
        filters.append(_filter(profile.id, "only", "types", episode_types=list(types)))
    for rule in bind.execute(sa.text(
        "SELECT * FROM download_profile_rules WHERE download_profile_id = :id ORDER BY position, id"
    ), {"id": profile.id}).mappings():
        pattern = rule["pattern"]
        if rule["field"] in ("title", "description") and rule["ignore_case"] and not (pattern or "").startswith("(?i)"):
            pattern = f"(?i){pattern or ''}"
        filters.append(_filter(
            profile.id, rule["action"], rule["field"],
            pattern=pattern if rule["field"] in ("title", "description") else None,
            duration_operator=rule["duration_operator"], duration_seconds=rule["duration_seconds"],
            episode_types=_json_which_episodes_filters(rule["episode_types"]), season_slugs=_json_which_episodes_filters(rule["season_slugs"]),
        ))
    date_line = _date_line(profile)
    if date_line is not None:
        filters.append(date_line)
    for position, item in enumerate(filters):
        item["position"] = position
    return filters


def _types_filter(filters: list[dict]) -> dict | None:
    return next((item for item in filters if item["field"] == "types" and item["action"] == "only"), None)


def _without_types(filters: list[dict]) -> list[tuple]:
    return [
        tuple(json.dumps(item[name], default=str) for name in _FILTER_COLUMNS if name not in ("download_profile_id", "position"))
        for item in filters if item is not _types_filter(filters)
    ]


def _merge_duplicates(bind, profiles, filters_by_profile: dict[int, list[dict]], titles: dict[int, str]) -> None:
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for profile in profiles:
        groups[(profile.collection_id, profile.local_media_profile_id)].append(profile)
    for (collection_id, _local_media_profile_id), group in groups.items():
        if len(group) < 2:
            continue
        keep, *others = sorted(group, key=lambda item: item.id)
        kept_filters = filters_by_profile[keep.id]
        for other in others:
            other_filters = filters_by_profile.pop(other.id)
            same = (
                all(getattr(keep, name) == getattr(other, name) for name in _PROFILE_SETTINGS)
                and _without_types(kept_filters) == _without_types(other_filters)
            )
            if same:
                kept_types, other_types = _types_filter(kept_filters), _types_filter(other_filters)
                if kept_types is not None and other_types is not None:
                    kept_types["episode_types"] = list(dict.fromkeys(
                        [*kept_types["episode_types"], *other_types["episode_types"]]
                    ))
                elif kept_types is not None:
                    # A profile without an episode types line downloads every type.
                    kept_filters.remove(kept_types)
                if other.enable_profile:
                    bind.execute(sa.text("UPDATE download_profiles SET enable_profile = 1 WHERE id = :id"), {"id": keep.id})
                logger.warning(
                    "Download Profile %s of %r merged into Download Profile %s: they differed only in their episode types",
                    other.id, titles.get(collection_id), keep.id,
                )
            else:
                logger.warning(
                    "Download Profile %s of %r removed: Download Profile %s already downloads this collection "
                    "to the same Local Media Profile, and a collection now has one profile per Local Media Profile",
                    other.id, titles.get(collection_id), keep.id,
                )
            ids = {"keep": keep.id, "remove": other.id}
            bind.execute(sa.text(
                "UPDATE media_downloads_episode SET download_profile_id = :keep WHERE download_profile_id = :remove"
            ), ids)
            bind.execute(sa.text("UPDATE import_steps SET download_profile_id = :keep WHERE download_profile_id = :remove"), ids)
            bind.execute(sa.text("DELETE FROM download_profile_rules WHERE download_profile_id = :remove"), ids)
            bind.execute(sa.text("DELETE FROM download_profile_seasons WHERE download_profile_id = :remove"), ids)
            bind.execute(sa.text("DELETE FROM download_profiles WHERE id = :remove"), ids)
        for position, item in enumerate(kept_filters):
            item["position"] = position


def _upgrade_which_episodes_filters() -> None:
    """Which episodes becomes one ordered list of filters, and a collection gets one Download Profile per Local Media Profile.

    The episode types, seasons and date window move from columns on download_profiles into
    rows of download_profile_filters, next to the profile's own rules: seasons first, then
    episode types, then the rules in their order, then the date line. Ignore case moves into
    the pattern as a leading (?i).

    Collections with more than one Download Profile for the same Local Media Profile keep one:
    profiles that differ only in their episode types become one profile with all of those
    types; otherwise the oldest stays and the others are removed, which the migration logs.
    """
    # SQLite keeps a created table even when the rest of this migration fails. While the old rules table is
    # still here nothing was converted yet, so a filters table that such an attempt left behind can go.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("download_profile_filters") and inspector.has_table("download_profile_rules"):
        op.drop_table("download_profile_filters")
    op.create_table(
        "download_profile_filters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "download_profile_id", sa.Integer(),
            sa.ForeignKey(
                "download_profiles.id", ondelete="CASCADE",
                name="fk_download_profile_filters_download_profile_id_download_profiles",
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, comment="Order of the line within the profile, from 0"),
        sa.Column("action", sa.String(16), nullable=False, comment="skip, only or keep"),
        sa.Column(
            "field", sa.String(16), nullable=False,
            comment="title, description, duration, types, seasons, published or downloaded",
        ),
        sa.Column(
            "pattern", sa.String(), nullable=True,
            comment="The regular expression of a title or description line; a leading (?i) ignores case",
        ),
        sa.Column("duration_operator", sa.String(16), nullable=True, comment="shorter or longer, for a duration line"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("episode_types", sa.JSON(), nullable=True, comment="The episode type keys of a types line"),
        sa.Column("season_slugs", sa.JSON(), nullable=True, comment="The season slugs of a seasons line"),
        sa.Column(
            "include_upcoming", sa.Boolean(), nullable=False, server_default="0",
            comment="A seasons line adds each new season to its slugs",
        ),
        sa.Column("days", sa.Integer(), nullable=True, comment="A published or downloaded line: the last N days"),
        sa.Column("count", sa.Integer(), nullable=True, comment="A published line: the latest N episodes"),
        sa.Column("starting_from", sa.Date(), nullable=True, comment="A published line: published since this day"),
    )
    op.create_index("ix_download_profile_filters_download_profile_id", "download_profile_filters", ["download_profile_id"])

    bind = op.get_bind()
    profiles = list(bind.execute(sa.text(
        "SELECT download_profiles.*, collections.episode_identifier AS collection_episode_identifier "
        "FROM download_profiles JOIN collections ON collections.id = download_profiles.collection_id "
        "ORDER BY download_profiles.id"
    )))
    titles = dict(bind.execute(sa.text("SELECT id, title FROM collections")).all())
    filters_by_profile = {
        profile.id: _filters_of(bind, profile, profile.collection_episode_identifier == "seasonal")
        for profile in profiles
    }
    _merge_duplicates(bind, profiles, filters_by_profile, titles)
    rows = [item for filters in filters_by_profile.values() for item in filters]
    if rows:
        table = sa.table(
            "download_profile_filters",
            *(sa.column(name, sa.JSON() if name in ("episode_types", "season_slugs") else sa.Date() if name == "starting_from" else None)
              for name in _FILTER_COLUMNS),
        )
        bind.execute(table.insert(), rows)

    op.drop_index("ix_download_profile_rules_download_profile_id", table_name="download_profile_rules")
    op.drop_table("download_profile_rules")
    op.drop_table("download_profile_seasons")
    with op.batch_alter_table("download_profiles") as batch:
        for name in (
            "ep_id_type_list", "download_days_in_past", "download_episode_count", "download_starting_from",
            "retention_from", "include_upcoming_seasons", "all_seasons",
        ):
            batch.drop_column(name)
        batch.create_unique_constraint(
            "uq_download_profiles_collection_local_media_profile", ["collection_id", "local_media_profile_id"],
        )


def _downgrade_which_episodes_filters() -> None:
    # The first episode types, seasons and date lines become the old columns again; every other filter a rule.
    op.create_table(
        "download_profile_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "download_profile_id", sa.Integer(),
            sa.ForeignKey(
                "download_profiles.id", ondelete="CASCADE",
                name="fk_download_profile_rules_download_profile_id_download_profiles",
            ),
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
        sa.Column("season_slugs", sa.JSON(), nullable=True, comment="The season slugs of a seasons rule"),
    )
    op.create_index("ix_download_profile_rules_download_profile_id", "download_profile_rules", ["download_profile_id"])
    op.create_table(
        "download_profile_seasons",
        sa.Column(
            "download_profile_id", sa.Integer(),
            sa.ForeignKey(
                "download_profiles.id", ondelete="CASCADE",
                name="fk_download_profile_seasons_download_profile_id_download_profiles",
            ),
            primary_key=True,
        ),
        sa.Column(
            "season_id", sa.Integer(),
            sa.ForeignKey("seasons.id", ondelete="CASCADE", name="fk_download_profile_seasons_season_id_seasons"),
            primary_key=True,
        ),
    )
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_constraint("uq_download_profiles_collection_local_media_profile", type_="unique")
        batch.add_column(sa.Column("ep_id_type_list", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("download_days_in_past", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("download_episode_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("download_starting_from", sa.Date(), nullable=True))
        batch.add_column(sa.Column(
            "retention_from", sa.String(16), nullable=False, server_default="published",
            comment="Whether a date window deletes episodes N days after publication or after downloading",
        ))
        batch.add_column(sa.Column("include_upcoming_seasons", sa.Boolean(), nullable=False, server_default="1"))
        batch.add_column(sa.Column(
            "all_seasons", sa.Boolean(), server_default="0", nullable=False,
            comment="The seasons line was removed: every season downloads, upcoming ones included",
        ))

    bind = op.get_bind()
    by_profile: dict[int, list] = defaultdict(list)
    for item in bind.execute(sa.text("SELECT * FROM download_profile_filters ORDER BY download_profile_id, position")).mappings():
        by_profile[item["download_profile_id"]].append(item)
    for profile_id, collection_id in bind.execute(sa.text("SELECT id, collection_id FROM download_profiles")).all():
        items = by_profile.get(profile_id, [])
        values: dict = {"id": profile_id, "types": "[]", "days": 0, "count": 0, "since": None, "retention": "published",
                        "upcoming": 1, "all": 1}
        rules = []
        seen: set[str] = set()
        for item in items:
            field = item["field"]
            first_only = item["action"] == "only" and field not in seen
            if first_only and field == "types":
                values["types"] = json.dumps(_json_which_episodes_filters(item["episode_types"]) or [])
            elif first_only and field == "seasons":
                values.update(all=0, upcoming=int(bool(item["include_upcoming"])))
                for slug in _json_which_episodes_filters(item["season_slugs"]) or []:
                    bind.execute(sa.text(
                        "INSERT INTO download_profile_seasons (download_profile_id, season_id) "
                        "SELECT :profile, id FROM seasons WHERE collection_id = :collection AND slug = :slug"
                    ), {"profile": profile_id, "collection": collection_id, "slug": slug})
            elif first_only and field in ("published", "downloaded"):
                values.update(
                    count=item["count"] or 0, days=item["days"] or 0, since=item["starting_from"],
                    retention="downloaded" if field == "downloaded" else "published",
                )
            elif field not in ("published", "downloaded"):
                pattern = item["pattern"]
                ignore_case = bool(pattern and pattern.startswith("(?i)"))
                rules.append({
                    "profile": profile_id, "position": len(rules), "action": item["action"], "field": field,
                    "pattern": pattern[len("(?i)"):] if ignore_case else pattern, "ignore_case": ignore_case,
                    "operator": item["duration_operator"], "seconds": item["duration_seconds"],
                    "types": json.dumps(_json_which_episodes_filters(item["episode_types"])) if item["episode_types"] is not None else None,
                    "slugs": json.dumps(_json_which_episodes_filters(item["season_slugs"])) if item["season_slugs"] is not None else None,
                })
            seen.add(field)
        bind.execute(sa.text(
            "UPDATE download_profiles SET ep_id_type_list = :types, download_days_in_past = :days, "
            "download_episode_count = :count, download_starting_from = :since, retention_from = :retention, "
            "include_upcoming_seasons = :upcoming, all_seasons = :all WHERE id = :id"
        ), values)
        for rule in rules:
            bind.execute(sa.text(
                "INSERT INTO download_profile_rules (download_profile_id, position, action, field, pattern, ignore_case, "
                "duration_operator, duration_seconds, episode_types, season_slugs) VALUES (:profile, :position, :action, "
                ":field, :pattern, :ignore_case, :operator, :seconds, :types, :slugs)"
            ), rule)

    op.drop_index("ix_download_profile_filters_download_profile_id", table_name="download_profile_filters")
    op.drop_table("download_profile_filters")


# --- source stream column (was 7e3b9d1a4c52) ---

def _upgrade_source_stream_column() -> None:
    """Stream profiles stream from any Source whose Site can stream, not only The Daily Wire.

    ``use_dw_stream`` becomes ``use_source_stream``; its values stay as they are.
    """
    with op.batch_alter_table("stream_profiles") as batch:
        batch.alter_column(
            "use_dw_stream", new_column_name="use_source_stream",
            comment="Stream episodes straight from their Source when the collection's Site can stream",
        )


def _downgrade_source_stream_column() -> None:
    with op.batch_alter_table("stream_profiles") as batch:
        batch.alter_column(
            "use_source_stream", new_column_name="use_dw_stream",
            comment="Use direct DW stream endpoints for stream",
        )


# --- daily wire resolutions (was 688634d39f23) ---

_PROFILE_FORMATS = {
    "format_360p": "format_480p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}


# A stream profile picks between downloads at 1080p and 720p.
_STREAM_FORMATS = {
    "format_360p": "format_720p",
    "format_480p": "format_720p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}


# Tables that hold one row per Collection and profile, by the columns that make a row unique with the profile.
_SCOPED = {
    "custom_index_states": ("collection_id",),
    "existing_file_scans": ("collection_id",),
    "collection_local_assets": ("collection_id", "asset_type", "file_path"),
    "import_steps": ("run_id", "collection_id"),
}


_PROFILE_TYPE_TABLES = ("local_media_profiles_collection", "local_media_profiles_movie", "local_media_profiles_video")


_DOWNLOAD_TYPE_TABLES = (
    "media_downloads_episode", "media_downloads_movie", "media_downloads_movie_extra", "media_downloads_video",
)


def _only_dailywire(profile_type: str, source_keys) -> bool:
    if profile_type == "movie":
        return True  # Only The Daily Wire has movies.
    if isinstance(source_keys, str):
        source_keys = json.loads(source_keys)
    return source_keys == ["dailywire"]


def _delete_download(bind, download_id: int) -> None:
    for table in ("media_download_assets", "media_download_history"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE media_download_id = :id"), {"id": download_id})
    for table in _DOWNLOAD_TYPE_TABLES:
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": download_id})
    bind.execute(sa.text("DELETE FROM media_downloads WHERE id = :id"), {"id": download_id})


def _merge(bind, duplicate: int, keeper: int) -> None:
    """Move everything of the duplicate profile to the keeper and delete it."""
    params = {"duplicate": duplicate, "keeper": keeper}
    keeper_sources = bind.execute(
        sa.text("SELECT source_keys FROM local_media_profiles WHERE id = :keeper"), params,
    ).scalar()
    if isinstance(keeper_sources, str):
        keeper_sources = json.loads(keeper_sources)
    if keeper_sources is not None and "dailywire" not in keeper_sources:
        bind.execute(
            sa.text("UPDATE local_media_profiles SET source_keys = :keys WHERE id = :keeper"),
            {**params, "keys": json.dumps(["dailywire", *keeper_sources])},
        )

    for (download_profile_id, collection_id) in bind.execute(sa.text(
            "SELECT id, collection_id FROM download_profiles WHERE local_media_profile_id = :duplicate"), params).all():
        kept = bind.execute(sa.text(
            "SELECT id FROM download_profiles WHERE local_media_profile_id = :keeper AND collection_id = :collection"),
            {**params, "collection": collection_id},
        ).scalar()
        if kept is None:
            bind.execute(sa.text("UPDATE download_profiles SET local_media_profile_id = :keeper WHERE id = :id"),
                         {**params, "id": download_profile_id})
            continue
        moved = {"old": download_profile_id, "new": kept}
        bind.execute(sa.text("UPDATE media_downloads_episode SET download_profile_id = :new WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("UPDATE import_steps SET download_profile_id = :new WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("DELETE FROM download_profile_filters WHERE download_profile_id = :old"), moved)
        bind.execute(sa.text("DELETE FROM download_profiles WHERE id = :old"), moved)

    for (download_id, media_item_id) in bind.execute(sa.text(
            "SELECT id, media_item_id FROM media_downloads WHERE local_media_profile_id = :duplicate"), params).all():
        held = bind.execute(sa.text(
            "SELECT 1 FROM media_downloads WHERE local_media_profile_id = :keeper AND media_item_id = :media"),
            {**params, "media": media_item_id},
        ).first()
        if held:
            _delete_download(bind, download_id)
        else:
            bind.execute(sa.text("UPDATE media_downloads SET local_media_profile_id = :keeper WHERE id = :id"),
                         {**params, "id": download_id})

    for table, columns in _SCOPED.items():
        same = " AND ".join(f"kept.{column} = {table}.{column}" for column in columns)
        bind.execute(sa.text(
            f"DELETE FROM {table} WHERE local_media_profile_id = :duplicate AND EXISTS ("
            f"SELECT 1 FROM {table} AS kept WHERE kept.local_media_profile_id = :keeper AND {same})"
        ), params)
        bind.execute(sa.text(f"UPDATE {table} SET local_media_profile_id = :keeper WHERE local_media_profile_id = :duplicate"), params)

    for table in _PROFILE_TYPE_TABLES:
        bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :duplicate"), params)
    bind.execute(sa.text("DELETE FROM local_media_profiles WHERE id = :duplicate"), params)


def _upgrade_daily_wire_resolutions() -> None:
    """The Daily Wire only offers 480p, 720p and 1080p.

    Local Media Profiles only for The Daily Wire, which includes every movie profile, and RSS stream
    profiles of Daily Wire collections, move to the nearest of those resolutions. They already
    downloaded these, as the Daily Wire has no others.

    A profile whose output template another profile of its type already uses at that resolution
    would download the same files, so it is merged into that profile: its downloads, Download Profiles
    and everything else it holds move there, except where that profile already holds the same.
    """
    bind = op.get_bind()
    profiles = bind.execute(sa.text(
        "SELECT id, type, output_template, preferred_format, source_keys FROM local_media_profiles ORDER BY id"
    )).all()
    for (profile_id, profile_type, template, preferred, source_keys) in profiles:
        target = _PROFILE_FORMATS.get(preferred)
        if target is None or not _only_dailywire(profile_type, source_keys):
            continue
        keeper = bind.execute(sa.text(
            "SELECT id FROM local_media_profiles WHERE type = :type AND output_template = :template "
            "AND preferred_format = :format AND id != :id"
        ), {"type": profile_type, "template": template, "format": target, "id": profile_id}).scalar()
        if keeper is None:
            bind.execute(sa.text("UPDATE local_media_profiles SET preferred_format = :format WHERE id = :id"),
                         {"format": target, "id": profile_id})
        else:
            _merge(bind, profile_id, keeper)

    for old, new in _STREAM_FORMATS.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles SET preferred_format = :new WHERE preferred_format = :old AND collection_id IN ("
            "SELECT id FROM collections WHERE source_key = 'dailywire')"
        ), {"old": old, "new": new})


def _downgrade_daily_wire_resolutions() -> None:
    # Every resolution was allowed before, so the profiles stay valid as they are.
    pass


# --- youtube stream resolutions (was 53adf1f1b502) ---

_FORMATS = {
    "format_480p": "format_720p",
    "format_1440p": "format_1080p",
    "format_4k": "format_1080p",
    "format_8k": "format_1080p",
}


def _upgrade_youtube_stream_resolutions() -> None:
    """RSS feeds can proxy a Site's video, and stream YouTube at 360p, 720p and 1080p only.

    RSS stream profiles get ``proxy_source_stream``, off. Profiles of YouTube collections that stream
    from YouTube move to the nearest of the resolutions it streams: 480p to 720p, 1440p and higher to
    1080p.
    """
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.add_column(sa.Column("proxy_source_stream", sa.Boolean(), nullable=False, server_default="0"))

    bind = op.get_bind()
    for old, new in _FORMATS.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles SET preferred_format = :new WHERE preferred_format = :old "
            "AND use_source_stream = :streams AND collection_id IN ("
            "SELECT id FROM collections WHERE source_key = 'ytdlp' AND ("
            "sharing_url LIKE '%youtube.com/%' OR sharing_url LIKE '%youtu.be/%'))"
        ), {"old": old, "new": new, "streams": True})


def _downgrade_youtube_stream_resolutions() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.drop_column("proxy_source_stream")


# --- hls feeds need hls video (was aa950d2ab545) ---

_MODES = {"audio_hls": "audio_mp4", "mp4_hls": "mp4"}


def _upgrade_hls_feeds_need_hls_video() -> None:
    """RSS feeds only serve HLS video from Sites that stream it or download it as an HLS bundle.

    Feeds of other Sites, such as NPO Start and every yt-dlp Site but YouTube, move from their HLS video
    output to the MP4 one that takes its place: audio_hls to audio_mp4, mp4_hls to mp4.
    """
    bind = op.get_bind()
    for old, new in _MODES.items():
        bind.execute(sa.text(
            "UPDATE stream_profiles_rss SET video_output_mode = :new WHERE video_output_mode = :old "
            "AND id IN (SELECT stream_profiles.id FROM stream_profiles JOIN collections "
            "ON collections.id = stream_profiles.collection_id "
            "WHERE collections.source_key != 'dailywire' AND NOT (collections.source_key = 'ytdlp' AND ("
            "collections.sharing_url LIKE '%youtube.com/%' OR collections.sharing_url LIKE '%youtu.be/%')))"
        ), {"old": old, "new": new})


def _downgrade_hls_feeds_need_hls_video() -> None:
    # The MP4 outputs keep working, so the feeds stay as they are.
    pass


# --- length upgrade checks (was d6346ad993ee) ---

def _upgrade_length_upgrade_checks() -> None:
    """The upgrade check can download a Daily Wire episode again when its length changed.

    Each download remembers the length of its file, and a Download Profile how many minutes longer or
    shorter count as a different length. Download Profiles of Daily Wire collections had no upgrade check
    before; they get it, counting a different length as the better version.
    """
    with op.batch_alter_table("media_downloads") as batch:
        batch.add_column(sa.Column(
            "duration", sa.Float(), nullable=True,
            comment="The length of the downloaded file in seconds; the media item's duration is the length the site lists",
        ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "upgrade_length_minutes", sa.Integer(), nullable=False, server_default="5",
            comment="How many minutes longer or shorter counts as a different length",
        ))
        batch.alter_column(
            "upgrade_improvements", existing_type=sa.JSON(), existing_nullable=False,
            comment="What counts as a better version: resolution, sponsorblock, subtitles, codec or length",
        )
    op.execute(sa.text(
        "UPDATE download_profiles SET upgrade_check = 1, upgrade_improvements = '[\"length\"]' "
        "WHERE collection_id IN (SELECT id FROM collections WHERE source_key = 'dailywire')"
    ))


def _downgrade_length_upgrade_checks() -> None:
    op.execute(sa.text(
        "UPDATE download_profiles SET upgrade_check = 0, upgrade_improvements = '[\"resolution\", \"sponsorblock\"]' "
        "WHERE collection_id IN (SELECT id FROM collections WHERE source_key = 'dailywire')"
    ))
    with op.batch_alter_table("download_profiles") as batch:
        batch.alter_column(
            "upgrade_improvements", existing_type=sa.JSON(), existing_nullable=False,
            comment="What counts as a better version: resolution, sponsorblock, subtitles or codec",
        )
        batch.drop_column("upgrade_length_minutes")
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("duration")


# --- proxy by default (was 28c70478078a) ---

def _upgrade_proxy_by_default() -> None:
    """RSS feeds proxy their Site's video through VODLoft by default.

    Through VODLoft, YouTube video plays most reliably, as VODLoft looks a refused link up again before the
    app notices, so feeds of YouTube now pass the video on through VODLoft unless the feed is set otherwise. Existing feeds of YouTube move to it too:
    they had it off only because that was the default. Other Sites have no choice, so it changes nothing there.
    """
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.alter_column("proxy_source_stream", existing_type=sa.Boolean(), existing_nullable=False, server_default="1")
    op.get_bind().execute(sa.text("UPDATE stream_profiles_rss SET proxy_source_stream = 1"))


def _downgrade_proxy_by_default() -> None:
    with op.batch_alter_table("stream_profiles_rss") as batch:
        batch.alter_column("proxy_source_stream", existing_type=sa.Boolean(), existing_nullable=False, server_default="0")


# --- episode order (was db11a36f288f) ---

_EPISODE_ORDER_COMMENT = "Which way the episodes are listed, within each season for a seasonal Collection: newest_first or oldest_first"


def _upgrade_episode_order() -> None:
    """A Collection chooses which way its episodes are listed.

    Seasonal Collections start each season at its first episode and every other Collection lists its
    newest episode first, the order the Collection page already showed.
    """
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("episode_order", sa.String(), nullable=True, comment=_EPISODE_ORDER_COMMENT))
    op.execute(sa.text(
        "UPDATE collections SET episode_order = CASE WHEN episode_identifier = 'seasonal' THEN 'oldest_first' ELSE 'newest_first' END"
    ))
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("episode_order", existing_type=sa.String(), nullable=False, existing_comment=_EPISODE_ORDER_COMMENT)


def _downgrade_episode_order() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("episode_order")


# --- drop append media type (was 7c3e9a1f5b2d) ---

def _upgrade_drop_append_media_type() -> None:
    """Local Media Profiles no longer keep append_media_type_to_filename.

    Templates say in Jinja whether a movie extra's file name ends in its media type, and
    nothing read the column any more.
    """
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("append_media_type_to_filename")


def _downgrade_drop_append_media_type() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "append_media_type_to_filename", sa.Boolean(), server_default="0", nullable=False,
        ))


# --- picture comments (was 8124198d716f) ---

_PICTURE_COMMENTS_COMMENT = (
    "A picture: the web address of an image at its Source, "
    "or thumbnails/<name>.jpg for an image VODLoft made itself and keeps in its thumbnail folder"
)


_TABLES = ("collections", "media_items_episode", "media_items_movie", "media_items_video", "movie_extra_sources")


_COLUMNS = ("background_image_path", "thumbnail_landscape_path", "thumbnail_portrait_path", "thumbnail_square_path")


def _set_comment(comment: str | None) -> None:
    # SQLite keeps no column comments, and changing one there would rebuild every table.
    if op.get_bind().dialect.name == "sqlite":
        return
    for table in _TABLES:
        for column in _COLUMNS:
            op.alter_column(table, column, existing_type=sa.String(), existing_nullable=True, comment=comment)


def _upgrade_picture_comments() -> None:
    """Describe what the picture columns hold.

    A picture column holds either the web address of an image at its Source, or the path of an image
    VODLoft made itself and keeps in its thumbnail folder.
    """
    _set_comment(_PICTURE_COMMENTS_COMMENT)


def _downgrade_picture_comments() -> None:
    _set_comment(None)


# --- profile lookup indexes (was 5b8e1f3c2a90) ---

_INDEXES = (
    ("ix_media_downloads_episode_download_profile_id", "media_downloads_episode", "download_profile_id"),
    ("ix_stream_profiles_collection_id", "stream_profiles", "collection_id"),
    ("ix_download_profiles_local_media_profile_id", "download_profiles", "local_media_profile_id"),
)


def _upgrade_profile_lookup_indexes() -> None:
    """Index the columns that find a profile's downloads and a collection's stream profiles.

    In a large library the profile tables and the download worker look these up for every profile, and
    without an index each lookup reads the whole table.
    """
    for name, table, column in _INDEXES:
        op.create_index(name, table, [column])


def _downgrade_profile_lookup_indexes() -> None:
    for name, table, _column in reversed(_INDEXES):
        op.drop_index(name, table_name=table)


# --- imported downloads join profiles (was a0eceaa70db5) ---

_PROFILE = """
    SELECT download_profiles.id
    FROM download_profiles
    JOIN media_downloads ON media_downloads.id = media_downloads_episode.id
    JOIN media_items_episode ON media_items_episode.id = media_downloads.media_item_id
    WHERE download_profiles.collection_id = media_items_episode.collection_id
      AND download_profiles.local_media_profile_id = media_downloads.local_media_profile_id
"""


def _upgrade_imported_downloads_join_profiles() -> None:
    """Give imported files to the Download Profile of their Collection and Local Media Profile.

    Files taken in by an importer or by matching existing files were recorded without a Download Profile.
    The profile only claimed them once it wanted their episode again, so a file whose episode was already
    outside the profile's date line was never deleted by its retention. Every such download now belongs to
    the Collection's Download Profile for its Local Media Profile, like a file the profile downloaded itself.
    """
    op.execute(f"""
        UPDATE media_downloads_episode
        SET download_profile_id = ({_PROFILE})
        WHERE download_profile_id IS NULL
          AND EXISTS (
              SELECT 1 FROM media_download_history
              WHERE media_download_history.media_download_id = media_downloads_episode.id
                AND media_download_history.action = 'imported'
          )
          AND EXISTS ({_PROFILE})
    """)


def _downgrade_imported_downloads_join_profiles() -> None:
    # Which downloads had no Download Profile before is not kept; they stay with their profile.
    pass


# --- locked media (was 7d3e9b2c41fa) ---

# What needs_subscription meant on each Source that set it.
_ACCESS_BY_SOURCE = {"npo": "npo_plus", "dailywire": "INSIDER", "ytdlp": "members"}


def _upgrade_locked_media() -> None:
    """Media items say which access they need, and when VODLoft checks whether locked media opened up.

    ``needs_subscription`` only knew one paid subscription per Source. It becomes ``access``, the key of
    the Source's Access the media needs, such as NPO Plus, a Daily Wire membership level or a YouTube
    channel membership. ``access_refused_at`` remembers that the Source refused a download for lack of
    it, and ``access_check_at`` and ``access_checks`` plan the checks for media that opens up later.
    """
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "access", sa.String(40), nullable=True,
            comment="Key of the Source's Access the media needs, such as NPO Plus or a channel membership",
        ))
        batch.add_column(sa.Column(
            "access_refused_at", sa.DateTime(), nullable=True,
            comment="When the Source last refused to give VODLoft the media for lack of its access",
        ))
        batch.add_column(sa.Column(
            "access_check_at", sa.DateTime(), nullable=True,
            comment="When VODLoft next checks whether locked media opened up",
        ))
        batch.add_column(sa.Column(
            "access_checks", sa.Integer(), nullable=False, server_default="0",
            comment="How often VODLoft checked whether the locked media opened up",
        ))
        batch.create_index("ix_media_items_access_check_at", ["access_check_at"])
    for source_key, access in _ACCESS_BY_SOURCE.items():
        op.execute(sa.text(
            "UPDATE media_items SET access = :access WHERE needs_subscription AND source_key = :source_key"
        ).bindparams(access=access, source_key=source_key))
    # A download the Source refused for lack of a subscription was kept from retrying by hand. The
    # media now stays locked by its access instead, so the download may come back once it opens up.
    op.execute(sa.text("""
        UPDATE media_downloads SET automatic_retry_suppressed = :suppressed
        WHERE automatic_retry_suppressed
          AND media_item_id IN (SELECT id FROM media_items WHERE needs_subscription)
          AND artifact_status = 'absent'
    """).bindparams(suppressed=False))
    # Elsewhere the Source refused a download: check soon whether the media opened up since.
    op.execute(
        "UPDATE media_items SET access_refused_at = CURRENT_TIMESTAMP, access_check_at = CURRENT_TIMESTAMP "
        "WHERE needs_subscription AND source_key <> 'npo'"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("needs_subscription")


def _downgrade_locked_media() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column(
            "needs_subscription", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="The Source only gives the media to a paying account, such as NPO Plus",
        ))
    op.execute("UPDATE media_items SET needs_subscription = (access IS NOT NULL)")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_index("ix_media_items_access_check_at")
        batch.drop_column("access_checks")
        batch.drop_column("access_check_at")
        batch.drop_column("access_refused_at")
        batch.drop_column("access")


# --- more sponsorblock types (was 4f7c2e9a1b38) ---

_ADDED = {"hook": "keep", "poi_highlight": "chapter", "chapter": "keep"}


_profiles = sa.table("download_profiles", sa.column("id", sa.Integer), sa.column("sponsorblock_segments", sa.JSON))


def _rewrite(change) -> None:
    connection = op.get_bind()
    for profile_id, segments in connection.execute(sa.select(_profiles.c.id, _profiles.c.sponsorblock_segments)).all():
        if isinstance(segments, str):
            segments = json.loads(segments)
        changed = change(dict(segments or {}))
        if changed != segments:
            connection.execute(
                _profiles.update().where(_profiles.c.id == profile_id).values(sponsorblock_segments=changed)
            )


def _upgrade_more_sponsorblock_types() -> None:
    """Give each Download Profile a choice for SponsorBlock's highlight, hook and viewer chapters.

    VODLoft always marked the highlight as a chapter when SponsorBlock was on, so it starts as Chapter and downloads
    stay as they were. VODLoft never asked for hooks and viewer chapters, so they start as Keep.
    """
    _rewrite(lambda segments: {**_ADDED, **segments})


def _downgrade_more_sponsorblock_types() -> None:
    _rewrite(lambda segments: {key: value for key, value in segments.items() if key not in _ADDED})


# --- library sort (was 5b3a9f9d5b51, 9c4e1a7d2f60 and 4a35f3a5b8ed) ---

_LIBRARY_SORT_COMMENT = (
    "How the user lists the Library's Collections: recently_used, often_used, name, release_date or added_at"
)


def _upgrade_library_sort() -> None:
    """Remember how often and when each Collection page is opened, and how each user lists the Library."""
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "open_count", sa.Integer(), nullable=False, server_default="0",
            comment="How often the Collection's page was opened",
        ))
        batch.add_column(sa.Column(
            "last_opened_at", sa.DateTime(timezone=True), nullable=True,
            comment="When the Collection's page was last opened",
        ))
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "library_collection_sort", sa.String(), nullable=False, server_default="recently_used",
            comment=_LIBRARY_SORT_COMMENT,
        ))
        batch.add_column(sa.Column(
            "library_collection_sort_reversed", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="Whether the user turned that order around",
        ))


def _downgrade_library_sort() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("library_collection_sort_reversed")
        batch.drop_column("library_collection_sort")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("last_opened_at")
        batch.drop_column("open_count")


# --- metadata refreshed at (was 80a8b55fb9d6) ---

_METADATA_REFRESHED_AT_COMMENT = "When VODLoft last looked the {} up at its Source, by a refresh or a manual Refresh now"


def _upgrade_metadata_refreshed_at() -> None:
    """Remember when each episode and video was last looked up at its Source.

    The metadata refresh sweep decides from it which items are due, so a restart no longer makes it look every
    unsettled item up again. Existing items start without a time: those with a refresh point already behind them are
    looked up once by the next sweep.
    """
    op.add_column("media_items_episode", sa.Column(
        "metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True, comment=_METADATA_REFRESHED_AT_COMMENT.format("episode"),
    ))
    op.add_column("media_items_video", sa.Column(
        "metadata_refreshed_at", sa.DateTime(timezone=True), nullable=True, comment=_METADATA_REFRESHED_AT_COMMENT.format("video"),
    ))


def _downgrade_metadata_refreshed_at() -> None:
    with op.batch_alter_table("media_items_video") as batch:
        batch.drop_column("metadata_refreshed_at")
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("metadata_refreshed_at")


# --- local media profile sites (was d3a7f1c9e2b5) ---

# The Sites VODLoft knows before it has anything from them: the ones a Source is made for, and YouTube, which
# yt-dlp takes an API key for. Only The Daily Wire's own Source downloads movies.
_SOURCE_SITES = {"dailywire": "dailywire", "npo": "npo"}


_BUILTIN_SITES = ("dailywire", "npo", "youtube")


_MOVIE_SITES = ("dailywire",)


def _keys(value) -> list[str] | None:
    if isinstance(value, str):
        value = json.loads(value)
    return value


def _sites_for(profile_type: str, source_keys: list[str] | None, known: list[str]) -> tuple[list[str], bool]:
    if source_keys is None:
        chosen, upcoming = known, True
    else:
        chosen = [site for site in known if site in {_SOURCE_SITES[key] for key in source_keys if key in _SOURCE_SITES}]
        upcoming = "ytdlp" in source_keys
        if upcoming:
            chosen = [site for site in known if site in chosen or site not in _SOURCE_SITES.values()]
    if profile_type == "movie":
        chosen = [site for site in chosen if site in _MOVIE_SITES]
    return chosen, upcoming


def _upgrade_local_media_profile_sites() -> None:
    """Offer Local Media Profiles per Site instead of per Source.

    A profile now lists the Sites it is offered for, such as YouTube or The Daily Wire, and whether Sites VODLoft
    sees later join that list. A profile offered for every Source gets every Site VODLoft knows and takes later
    Sites too. A profile limited to some Sources gets the Sites of those Sources: yt-dlp stands for every Site that
    is not The Daily Wire or NPO Start, and for the Sites VODLoft sees later.
    """
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "site_keys", sa.JSON(), nullable=False, server_default="[]",
            comment="The Sites this profile is offered for",
        ))
        batch.add_column(sa.Column(
            "include_upcoming_sites", sa.Boolean(), nullable=False, server_default=sa.true(),
            comment="Sites VODLoft sees for the first time join the profile's Sites",
        ))

    bind = op.get_bind()
    recorded = bind.execute(sa.text("SELECT key FROM sites")).scalars().all()
    known = sorted({*_BUILTIN_SITES, *recorded})
    profiles = bind.execute(sa.text("SELECT id, type, source_keys FROM local_media_profiles")).all()
    for profile_id, profile_type, source_keys in profiles:
        chosen, upcoming = _sites_for(profile_type, _keys(source_keys), known)
        bind.execute(
            sa.text("UPDATE local_media_profiles SET site_keys = :sites, include_upcoming_sites = :upcoming WHERE id = :id"),
            {"sites": json.dumps(chosen), "upcoming": upcoming, "id": profile_id},
        )

    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("source_keys")


def _downgrade_local_media_profile_sites() -> None:
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "source_keys", sa.JSON(), nullable=True,
            comment="The Sources this profile is offered for; NULL offers it for every Source",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("include_upcoming_sites")
        batch.drop_column("site_keys")


# --- settings on local media profiles (was e8b2c4f6a1d3) ---

# Neither The Daily Wire nor NPO Start has auto-generated subtitles; only YouTube has SponsorBlock.
_WITHOUT_AUTO_SUBTITLES = {"dailywire", "npo"}


_SPONSORBLOCK_SITE = "youtube"


# What a profile without YouTube Download Profiles keeps, with SponsorBlock off.
_SEGMENTS = {
    "sponsor": "chapter", "selfpromo": "keep", "interaction": "keep", "intro": "chapter", "outro": "chapter",
    "preview": "keep", "filler": "keep", "hook": "keep", "music_offtopic": "keep", "poi_highlight": "chapter",
    "chapter": "keep",
}


def _json_settings_on_local_media_profiles(value):
    return json.loads(value) if isinstance(value, str) else value


def _upgrade_settings_on_local_media_profiles() -> None:
    """Keep auto-generated subtitles and SponsorBlock on Local Media Profiles instead of on Download Profiles.

    Manual downloads have no Download Profile, so they could never use these settings. Each Local Media Profile
    now keeps them, and they apply on the Sites that have them. A profile takes what most of its Download Profiles
    on those Sites had.
    """
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), nullable=False, server_default="fallback",
            comment="Auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=False, server_default="{}",
            comment="SponsorBlock segment type to keep, chapter or cut",
        ))

    bind = op.get_bind()
    # Only The Daily Wire's and NPO Start's collections have their Site yet: a background migration finds the Site
    # of yt-dlp collections after this migration ran. A YouTube collection is still known by its link.
    rows = bind.execute(sa.text(
        "SELECT download_profiles.local_media_profile_id, "
        "CASE WHEN collections.site_key IS NOT NULL THEN collections.site_key "
        "WHEN collections.source_key = 'ytdlp' AND (collections.sharing_url LIKE '%youtube.com/%' "
        "OR collections.sharing_url LIKE '%youtu.be/%') THEN 'youtube' END, download_profiles.auto_subtitles, "
        "download_profiles.sponsorblock_enabled, download_profiles.sponsorblock_segments "
        "FROM download_profiles JOIN collections ON collections.id = download_profiles.collection_id "
        "ORDER BY download_profiles.id"
    )).all()
    auto_subtitles: dict[int, Counter] = defaultdict(Counter)
    sponsorblock: dict[int, Counter] = defaultdict(Counter)
    for profile_id, site_key, auto, enabled, segments in rows:
        if site_key not in _WITHOUT_AUTO_SUBTITLES:
            auto_subtitles[profile_id][auto] += 1
        if site_key == _SPONSORBLOCK_SITE:
            sponsorblock[profile_id][(bool(enabled), json.dumps(_json_settings_on_local_media_profiles(segments) or {}, sort_keys=True))] += 1

    for (profile_id,) in bind.execute(sa.text("SELECT id FROM local_media_profiles")).all():
        # The most common choice; on a tie, the one of the oldest Download Profile.
        auto = auto_subtitles[profile_id].most_common(1)[0][0] if auto_subtitles[profile_id] else "fallback"
        if sponsorblock[profile_id]:
            enabled, segments = sponsorblock[profile_id].most_common(1)[0][0]
            segments = {**_SEGMENTS, **json.loads(segments)}
        else:
            enabled, segments = False, _SEGMENTS
        bind.execute(
            sa.text(
                "UPDATE local_media_profiles SET auto_subtitles = :auto, sponsorblock_enabled = :enabled, "
                "sponsorblock_segments = :segments WHERE id = :id"
            ),
            {"auto": auto, "enabled": enabled, "segments": json.dumps(segments), "id": profile_id},
        )

    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("auto_subtitles")
        batch.drop_column("sponsorblock_enabled")
        batch.drop_column("sponsorblock_segments")


def _downgrade_settings_on_local_media_profiles() -> None:
    with op.batch_alter_table("download_profiles") as batch:
        batch.add_column(sa.Column(
            "auto_subtitles", sa.String(16), nullable=False, server_default="fallback",
            comment="YouTube's auto-generated subtitles: never, fallback (when there is no real one) or always",
        ))
        batch.add_column(sa.Column("sponsorblock_enabled", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column(
            "sponsorblock_segments", sa.JSON(), nullable=False, server_default="{}",
            comment="SponsorBlock segment type to keep, chapter or cut out, for YouTube Collections",
        ))
    with op.batch_alter_table("local_media_profiles") as batch:
        batch.drop_column("sponsorblock_segments")
        batch.drop_column("sponsorblock_enabled")
        batch.drop_column("auto_subtitles")
