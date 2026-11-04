"""Which episodes becomes one ordered list of filters, and a collection gets one Download Profile per Local Media Profile.

The episode types, seasons and date window move from columns on download_profiles into
rows of download_profile_filters, next to the profile's own rules: seasons first, then
episode types, then the rules in their order, then the date line. Ignore case moves into
the pattern as a leading (?i).

Collections with more than one Download Profile for the same Local Media Profile keep one:
profiles that differ only in their episode types become one profile with all of those
types; otherwise the oldest stays and the others are removed, which the migration logs.

Revision ID: cbad9977fd7b
Revises: ce5df2342e6f
Create Date: 2026-11-04
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "cbad9977fd7b"
down_revision = "ce5df2342e6f"
branch_labels = None
depends_on = None

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


def _json(value):
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
        return _filter(profile.id, "only", "published", starting_from=profile.download_starting_from)
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
    types = _json(profile.ep_id_type_list) or []
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
            episode_types=_json(rule["episode_types"]), season_slugs=_json(rule["season_slugs"]),
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


def upgrade() -> None:
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


def downgrade() -> None:
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
                values["types"] = json.dumps(_json(item["episode_types"]) or [])
            elif first_only and field == "seasons":
                values.update(all=0, upcoming=int(bool(item["include_upcoming"])))
                for slug in _json(item["season_slugs"]) or []:
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
                    "types": json.dumps(_json(item["episode_types"])) if item["episode_types"] is not None else None,
                    "slugs": json.dumps(_json(item["season_slugs"])) if item["season_slugs"] is not None else None,
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
