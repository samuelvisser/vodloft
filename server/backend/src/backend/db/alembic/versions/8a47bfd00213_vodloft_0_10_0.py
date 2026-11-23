"""Upgrade the VODLoft 0.9.1 schema to 0.10.0.

Revision ID: 8a47bfd00213
Revises: 5b8e2d4c9a17
Create Date: 2026-11-23

The single release migration for 0.10.0. It takes a 0.9.1 database straight to 0.10.0; each step's docstring says
what it does. The pre-releases of 0.10.0 tried several designs for channels and creators before 0.10.0 settled on
independent collections that a creator only groups. A 0.9.1 database has none of those, so this migration only
creates the tables and columns 0.10.0 has, and converts what 0.9.1 stored. It keeps the revision of the last
pre-release migration, so a test database that ran those is already current.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "8a47bfd00213"
down_revision = "5b8e2d4c9a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _upgrade_movie_profiles_become_video_profiles()
    _upgrade_podcast_and_series_scope()
    _upgrade_profile_options()
    _upgrade_creators()
    _upgrade_collection_lists()
    _upgrade_split_chapters()
    _upgrade_episodes_without_usable_media()
    _upgrade_retention()
    _upgrade_sites_in_order()
    _upgrade_api_key_note()
    _upgrade_new_lists_rule()
    _upgrade_season_origin()


def downgrade() -> None:
    _downgrade_season_origin()
    _downgrade_new_lists_rule()
    _downgrade_api_key_note()
    _downgrade_sites_in_order()
    _downgrade_retention()
    # Episodes without usable media that were removed or kept stay as they are.
    _downgrade_split_chapters()
    _downgrade_collection_lists()
    _downgrade_creators()
    _downgrade_profile_options()
    _downgrade_podcast_and_series_scope()
    _downgrade_movie_profiles_become_video_profiles()


# Movie profiles become Video profiles.

_KEPT_APART = "{# kept apart from {name} #}"


def _upgrade_movie_profiles_become_video_profiles() -> None:
    """One Video profile type keeps single videos, and movies with their extras. Every Movie profile moves to it and
    keeps its own Sites: it stops taking Sites VODLoft sees for the first time, since those only have single videos.
    A Movie profile that has the same template and format as a Video profile gets a Jinja comment at the end of its
    template, which names no file differently, so the two stay apart.

    A Video profile says what it is offered for: videos, movies or both. The two profiles every installation starts
    with keep what they were made for, unless they already hold downloads of the other kind."""
    bind = op.get_bind()
    profiles = sa.table(
        "local_media_profiles",
        sa.column("id", sa.Integer), sa.column("type", sa.String), sa.column("name", sa.String),
        sa.column("output_template", sa.String), sa.column("preferred_format", sa.String),
        sa.column("include_upcoming_sites", sa.Boolean),
    )
    video_keys = {
        (row.output_template, row.preferred_format): row.name
        for row in bind.execute(sa.select(profiles).where(profiles.c.type == "video"))
    }
    for row in bind.execute(sa.select(profiles).where(profiles.c.type == "movie")).all():
        clash = video_keys.get((row.output_template, row.preferred_format))
        if clash is not None:
            bind.execute(
                profiles.update().where(profiles.c.id == row.id)
                .values(output_template=row.output_template + _KEPT_APART.replace("{name}", clash.replace("#}", "")))
            )
    bind.execute(sa.text("INSERT INTO local_media_profiles_video (id) SELECT id FROM local_media_profiles_movie"))
    bind.execute(
        profiles.update().where(profiles.c.type == "movie").values(type="video", include_upcoming_sites=False)
    )
    op.drop_table("local_media_profiles_movie")

    op.add_column("local_media_profiles_video", sa.Column(
        "video_scope", sa.String(16), nullable=False, server_default="both",
        comment="What the profile is offered for: videos, movies or both",
    ))
    op.execute(
        "UPDATE local_media_profiles_video SET video_scope = 'movies' "
        "WHERE id IN (SELECT id FROM local_media_profiles WHERE slug = 'vodloft-movies') "
        "AND id NOT IN (SELECT local_media_profile_id FROM media_downloads WHERE type = 'video' "
        "AND local_media_profile_id IS NOT NULL)"
    )
    op.execute(
        "UPDATE local_media_profiles_video SET video_scope = 'videos' "
        "WHERE id IN (SELECT id FROM local_media_profiles WHERE slug = 'vodloft-videos') "
        "AND id NOT IN (SELECT local_media_profile_id FROM media_downloads "
        "WHERE type IN ('movie', 'movie_extra') AND local_media_profile_id IS NOT NULL)"
    )


def _downgrade_movie_profiles_become_video_profiles() -> None:
    # Former Movie profiles cannot be told apart again, so they stay Video profiles.
    with op.batch_alter_table("local_media_profiles_video") as batch:
        batch.drop_column("video_scope")
    op.create_table(
        "local_media_profiles_movie",
        sa.Column("id", sa.Integer(), sa.ForeignKey("local_media_profiles.id", ondelete="CASCADE"), primary_key=True),
    )


# Podcasts and Series.

def _upgrade_podcast_and_series_scope() -> None:
    """The Available for choice "Podcasts and Series" was stored as "both". It is now stored as
    "podcast-and-series"."""
    _rename_scope("both", "podcast-and-series")


def _downgrade_podcast_and_series_scope() -> None:
    _rename_scope("podcast-and-series", "both")


def _rename_scope(old: str, new: str) -> None:
    op.execute(f"UPDATE local_media_profiles_collection SET collection_scope = '{new}' WHERE collection_scope = '{old}'")
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        batch.alter_column("collection_scope", existing_type=sa.String(), existing_nullable=False, server_default=new)


# Profile options from ytdl-sub.

def _upgrade_profile_options() -> None:
    """A Local Media Profile can keep the chapters a video comes with, cut out chapters by their title, and save the
    site's info file beside the media. A Collection profile can give episodes a title and description of its own in
    their metadata, and say whether its NFO files call them episodes or music videos. A Download Profile's published
    line can end on a date.

    Profiles that already exist keep doing what they did: they leave the chapters out unless SponsorBlock adds some.
    New profiles start with the chapters kept."""
    op.add_column("local_media_profiles", sa.Column(
        "keep_chapters", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Keep the chapters the video comes with",
    ))
    op.add_column("local_media_profiles", sa.Column(
        "cut_chapters", sa.JSON(), nullable=False, server_default="[]",
        comment="Regular expressions: a chapter whose title matches one is cut out",
    ))
    op.add_column("local_media_profiles", sa.Column(
        "save_info_json", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Save the site's info file, which yt-dlp writes, beside the media",
    ))
    for name, what in (("episode_title_template", "title"), ("episode_description_template", "description")):
        op.add_column("local_media_profiles_collection", sa.Column(
            name, sa.Text(), nullable=True,
            comment=f"A Jinja template for each episode's {what} in its NFO and embedded metadata",
        ))
    op.add_column("local_media_profiles_collection", sa.Column(
        "episode_nfo", sa.String(16), nullable=False, server_default="episode",
        comment="What each episode's NFO file and embedded metadata call it: episode or music_video",
    ))
    op.add_column("download_profile_filters", sa.Column(
        "until", sa.Date(), nullable=True, comment="A published line: published on or before this day",
    ))
    op.add_column("media_downloads", sa.Column(
        "cut_chapters", sa.JSON(), nullable=True,
        comment="The chapters of the video as published that were cut out by their title",
    ))


def _downgrade_profile_options() -> None:
    with op.batch_alter_table("media_downloads") as batch:
        batch.drop_column("cut_chapters")
    with op.batch_alter_table("download_profile_filters") as batch:
        batch.drop_column("until")
    with op.batch_alter_table("local_media_profiles_collection") as batch:
        for column in ("episode_nfo", "episode_description_template", "episode_title_template"):
            batch.drop_column(column)
    with op.batch_alter_table("local_media_profiles") as batch:
        for column in ("save_info_json", "cut_chapters", "keep_chapters"):
            batch.drop_column(column)


# Creators.

def _upgrade_creators() -> None:
    """A creator groups channel collections in the Library: who made the work, whatever each Site calls them, with
    an account on each of their Sites. A movie can belong to a creator, such as a Daily Wire host's movie."""
    op.create_table(
        "creators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True),
        sa.Column("banner_path", sa.String(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=False, server_default="[]", comment="The creator's own links"),
        sa.Column("facts", sa.JSON(), nullable=False, server_default="[]", comment='Short facts, such as "1.2M subscribers"'),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column("genre", sa.String(), nullable=True, comment="Given to the creator's collections, for their NFO files"),
        sa.Column(
            "content_rating", sa.String(), nullable=True, comment="Given to the creator's collections, for their NFO files",
        ),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0", comment="How often the creator's page was opened"),
        sa.Column(
            "last_opened_at", sa.DateTime(timezone=True), nullable=True, comment="When the creator's page was last opened",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"], name="fk_creators_added_by_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_creators"),
    )
    op.create_index("ix_creators_uuid", "creators", ["uuid"], unique=True)
    op.create_index("ix_creators_slug", "creators", ["slug"], unique=True)
    op.create_table(
        "creator_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False, comment="Id of the Source that looks the account up"),
        sa.Column("site_key", sa.String(), nullable=False),
        sa.Column("site_ref", sa.String(), nullable=False, comment="The Site's own id for the account"),
        sa.Column(
            "url", sa.String(), nullable=True,
            comment="The account's page; empty when the Site has none, such as a Daily Wire host",
        ),
        sa.Column("handle", sa.String(), nullable=True),
        sa.Column("avatar_path", sa.String(), nullable=True, comment="The account's own picture on its Site"),
        sa.Column("banner_path", sa.String(), nullable=True, comment="The account's own banner on its Site"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], name="fk_creator_accounts_creator_id_creators", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["site_key"], ["sites.key"], name="fk_creator_accounts_site_key_sites"),
        sa.PrimaryKeyConstraint("id", name="pk_creator_accounts"),
        sa.UniqueConstraint("site_key", "site_ref", name="uq_creator_account_site_ref"),
    )
    op.create_index("ix_creator_accounts_creator_id", "creator_accounts", ["creator_id"])
    op.create_index("ix_creator_accounts_site_key", "creator_accounts", ["site_key"])
    with op.batch_alter_table("media_items_movie") as batch:
        batch.add_column(sa.Column("creator_id", sa.Integer(), nullable=True, comment="The creator the movie belongs to"))
        batch.create_foreign_key(
            "fk_media_items_movie_creator_id_creators", "creators", ["creator_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_media_items_movie_creator_id", ["creator_id"])


def _downgrade_creators() -> None:
    with op.batch_alter_table("media_items_movie") as batch:
        batch.drop_index("ix_media_items_movie_creator_id")
        batch.drop_constraint("fk_media_items_movie_creator_id_creators", type_="foreignkey")
        batch.drop_column("creator_id")
    op.drop_table("creator_accounts")
    op.drop_table("creators")


# Channel and list collections.

def _upgrade_collection_lists() -> None:
    """A collection's own link is a channel or one list. Its kind is told from its link by a background migration, as
    only its Source can tell; until then every collection is a channel collection. A channel collection can be in a
    creator, and can make the channel's lists, such as its playlists or an artist's albums, seasons. Its channel season
    holds what is in none of them. A collection checks duplicates only among its own seasons, and can give a video in
    several of its seasons an episode in each, as an artist's albums each show every track they have.

    A collection can hold only the videos of its lists, so its own link may be empty, and the user can put its seasons
    in their own order. 0.9.1 collections have no lists, so every setting starts at its default."""
    op.create_table(
        "collection_lists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False, comment="The Site's own id for the playlist"),
        sa.Column(
            "source_key", sa.String(), nullable=False, comment="Id of the Source that reads the list, as registered in sources",
        ),
        sa.Column("site_key", sa.String(), nullable=True, comment="The Site the list is on"),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column(
            "site_position", sa.Integer(), nullable=False, server_default="0", comment="Where the Site lists it, newest first",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default="1",
            comment="Whether the playlist is a season, when only selected playlists are",
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="known",
            comment="known, or new while it waits for the user's choice",
        ),
        sa.Column(
            "as_season", sa.Boolean(), nullable=False, server_default="1",
            comment="Whether the list is a season of its own, or its videos join the collection's other seasons",
        ),
        sa.Column(
            "added_by_user", sa.Boolean(), nullable=False, server_default="0",
            comment="The user added the link, rather than it being one of the playlists of the collection's channel",
        ),
        sa.Column(
            "season_id", sa.Integer(), nullable=True,
            comment="The list's season, once it has one, which other lists of the collection may share",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["collections.id"], name="fk_collection_lists_collection_id_collections", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["season_id"], ["seasons.id"], name="fk_collection_lists_season_id_seasons", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["site_key"], ["sites.key"], name="fk_collection_lists_site_key_sites"),
        sa.PrimaryKeyConstraint("id", name="pk_collection_lists"),
        sa.UniqueConstraint("collection_id", "ref", name="uq_collection_list_ref"),
    )
    op.create_index("ix_collection_lists_collection_id", "collection_lists", ["collection_id"])
    op.create_table(
        "collection_list_items",
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0",
            comment="Where the playlist lists the video, from 0: its order at its Site",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"], ["collection_lists.id"], name="fk_collection_list_items_list_id_collection_lists",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "source_slug", name="pk_collection_list_items"),
    )

    with op.batch_alter_table("collections") as batch:
        batch.alter_column(
            "sharing_url", existing_type=sa.String(), nullable=True,
            comment="The collection's own link; a collection that only holds its link seasons may go without",
        )
        batch.add_column(sa.Column(
            "kind", sa.String(), nullable=False, server_default="channel",
            comment="What its own link is: channel, a creator's page of all their uploads, or list, one list or no link",
        ))
        batch.add_column(sa.Column(
            "creator_id", sa.Integer(), nullable=True,
            comment="The creator it is grouped under in the Library, for a channel collection",
        ))
        batch.create_foreign_key("fk_collections_creator_id_creators", "creators", ["creator_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_collections_creator_id", ["creator_id"])
        batch.add_column(sa.Column(
            "link_seasons", sa.String(), nullable=False, server_default="off",
            comment="Whether the channel's playlists are seasons: off, all or selected",
        ))
        batch.add_column(sa.Column(
            "new_lists", sa.JSON(), nullable=False, server_default="{}",
            comment=(
                "What happens with a list the channel adds, by the kind of list, when only selected lists are seasons: "
                "ask, add or ignore"
            ),
        ))
        batch.add_column(sa.Column(
            "list_layout", sa.String(), nullable=False, server_default="season_each",
            comment="How the lists that are seasons are laid out: season_each, or by_year in a season per upload year",
        ))
        batch.add_column(sa.Column(
            "loose_videos", sa.String(), nullable=False, server_default="one_season",
            comment="Where the channel's own videos go: one_season, the channel season, or by_year",
        ))
        batch.add_column(sa.Column(
            "channel_season", sa.String(), nullable=False, server_default="unlisted",
            comment="What the channel season holds: everything, every video of the feeds, or unlisted, those in no list",
        ))
        batch.add_column(sa.Column(
            "repeat_videos", sa.String(), nullable=False, server_default="one_season",
            comment=(
                "What happens with a video that belongs in several of its seasons: one_season, an episode in the first, "
                "or each_season, an episode in each"
            ),
        ))
        batch.add_column(sa.Column(
            "outside_videos", sa.String(), nullable=False, server_default="leave_out",
            comment=(
                "What happens with the videos of the playlists that are seasons that the collection's own link does "
                "not list: leave_out, add, or only, which holds nothing but the videos of those playlists"
            ),
        ))
        batch.add_column(sa.Column(
            "feeds", sa.JSON(), nullable=True,
            comment=(
                "For a channel collection, the refs of the channel's feeds it lists, such as only a YouTube channel's "
                "Videos; null lists every feed"
            ),
        ))
        batch.add_column(sa.Column(
            "custom_season_order", sa.Boolean(), nullable=False, server_default="0",
            comment="The user put the seasons in their own order, so a new season goes last instead of where its date puts it",
        ))
    with op.batch_alter_table("seasons") as batch:
        batch.add_column(sa.Column(
            "loose", sa.Boolean(), nullable=False, server_default="0",
            comment="Holds the collection's videos that are in none of the playlists that are its seasons",
        ))
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "from_link_season", sa.Boolean(), nullable=False, server_default="0",
            comment="Added because a playlist that is a season lists it, not the collection's own link",
        ))
        batch.drop_constraint("uq_episode_collection_source_slug", type_="unique")
        batch.create_unique_constraint("uq_episode_season_source_slug", ["season_id", "source_slug"])


def _downgrade_collection_lists() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_constraint("uq_episode_season_source_slug", type_="unique")
        batch.create_unique_constraint("uq_episode_collection_source_slug", ["collection_id", "source_slug"])
        batch.drop_column("from_link_season")
    with op.batch_alter_table("seasons") as batch:
        batch.drop_column("loose")
    with op.batch_alter_table("collections") as batch:
        for column in (
            "custom_season_order", "feeds", "outside_videos", "repeat_videos", "channel_season", "loose_videos",
            "list_layout", "new_lists", "link_seasons",
        ):
            batch.drop_column(column)
        batch.drop_index("ix_collections_creator_id")
        batch.drop_constraint("fk_collections_creator_id_creators", type_="foreignkey")
        batch.drop_column("creator_id")
        batch.drop_column("kind")
    # A collection without a link of its own cannot go back to 0.9.1.
    op.execute("DELETE FROM collections WHERE sharing_url IS NULL")
    with op.batch_alter_table("collections") as batch:
        batch.alter_column("sharing_url", existing_type=sa.String(), nullable=False, comment=None)
    op.drop_table("collection_list_items")
    op.drop_index("ix_collection_lists_collection_id", table_name="collection_lists")
    op.drop_table("collection_lists")


# Split downloads.

def _upgrade_split_chapters() -> None:
    """A collection can split each new video with chapters into a part per chapter, and an episode remembers which
    video and which stretch of it it is."""
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "split_chapters", sa.Boolean(), nullable=False, server_default="0",
            comment="Each new video with chapters becomes a season of its own, with an episode per chapter",
        ))
    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "part_of", sa.String(), nullable=True,
            comment="The Source's slug of the video the episode is one part of, when its collection splits videos by chapter",
        ))
        batch.add_column(sa.Column("part_start", sa.Float(), nullable=True, comment="Where the part starts in its video, in seconds"))
        batch.add_column(sa.Column("part_end", sa.Float(), nullable=True, comment="Where the part ends in its video, in seconds"))


def _downgrade_split_chapters() -> None:
    with op.batch_alter_table("media_items_episode") as batch:
        for column in ("part_end", "part_start", "part_of"):
            batch.drop_column(column)
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("split_chapters")


# Episodes without usable media.

_EPISODES = "media_items_episode"
_NO_USABLE_MEDIA_KEYS = ("no_usable_media.reason", "no_usable_media.since", "no_usable_media.previous_identifier")


def _upgrade_episodes_without_usable_media() -> None:
    """An episode without usable media becomes an episode its Source no longer has. One that has no files is deleted.
    One with files keeps them: it is marked removed from its Source, as published, and the Home page asks whether to
    keep it. It gets back the identifier it had before, or a new aux identifier when another episode took that one."""
    connection = op.get_bind()
    episodes = connection.execute(sa.text(
        f"SELECT e.id, e.collection_id, e.episode_identifier, e.published_date, c.episode_identifier AS collection_identifier "
        f"FROM {_EPISODES} e JOIN collections c ON c.id = e.collection_id "
        "WHERE e.publish_status = 'no_usable_media' ORDER BY e.id"
    )).all()
    for episode in episodes:
        has_files = connection.execute(
            sa.text("SELECT 1 FROM media_downloads WHERE media_item_id = :id"), {"id": episode.id},
        ).first() is not None
        if has_files:
            _keep_unusable_episode(connection, episode)
        else:
            _delete_unusable_episode(connection, episode.id)
    connection.execute(sa.text(
        "DELETE FROM metadata WHERE parent_table = 'collections' AND key = 'ep_id.latest_not_usable_num'"
    ))


def _meta(connection, parent_table: str, parent_id: int, key: str) -> str | None:
    return connection.execute(
        sa.text("SELECT value FROM metadata WHERE parent_table = :table AND parent_id = :id AND key = :key"),
        {"table": parent_table, "id": parent_id, "key": key},
    ).scalar()


def _set_collection_meta(connection, collection_id: int, key: str, value: str) -> None:
    updated = connection.execute(
        sa.text("UPDATE metadata SET value = :value WHERE parent_table = 'collections' AND parent_id = :id AND key = :key"),
        {"value": value, "id": collection_id, "key": key},
    ).rowcount
    if not updated:
        now = datetime.now(timezone.utc)
        connection.execute(
            sa.text(
                "INSERT INTO metadata (parent_table, parent_id, key, value, created_at, updated_at) "
                "VALUES ('collections', :id, :key, :value, :now, :now)"
            ),
            {"id": collection_id, "key": key, "value": value, "now": now},
        )


def _identifier_free(connection, collection_id: int, identifier: str) -> bool:
    return connection.execute(
        sa.text(f"SELECT 1 FROM {_EPISODES} WHERE collection_id = :collection AND episode_identifier = :identifier"),
        {"collection": collection_id, "identifier": identifier},
    ).first() is None


def _new_aux(connection, collection_id: int) -> str:
    numbers = [int(_meta(connection, "collections", collection_id, "ep_id.latest_aux_num") or 0)]
    for (identifier,) in connection.execute(
        sa.text(f"SELECT episode_identifier FROM {_EPISODES} WHERE collection_id = :collection AND episode_identifier LIKE 'aux.%'"),
        {"collection": collection_id},
    ):
        payload = identifier.partition(".")[2]
        if payload.isdigit():
            numbers.append(int(payload))
    number = max(numbers) + 1
    _set_collection_meta(connection, collection_id, "ep_id.latest_aux_num", str(number))
    return f"aux.{number}"


def _as_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _keep_unusable_episode(connection, episode) -> None:
    identifier = episode.episode_identifier
    if identifier.startswith("not-usable."):
        previous = _meta(connection, _EPISODES, episode.id, "no_usable_media.previous_identifier")
        if previous and _identifier_free(connection, episode.collection_id, previous):
            identifier = previous
            published = _as_utc(episode.published_date)
            if previous.startswith("ep.") and episode.collection_identifier == "date_based" and published is not None:
                head = int(_meta(connection, "collections", episode.collection_id, "ep_id.latest_ep_date") or 0)
                _set_collection_meta(
                    connection, episode.collection_id, "ep_id.latest_ep_date", str(max(head, int(published.timestamp()))),
                )
        else:
            identifier = _new_aux(connection, episode.collection_id)
    connection.execute(
        sa.text(
            f"UPDATE {_EPISODES} SET publish_status = 'published_final', episode_identifier = :identifier, "
            "metadata_is_final = :false WHERE id = :id"
        ),
        {"identifier": identifier, "id": episode.id, "false": False},
    )
    connection.execute(sa.text("UPDATE media_items SET removed_from_source = :true WHERE id = :id"), {"true": True, "id": episode.id})
    connection.execute(
        sa.text("DELETE FROM metadata WHERE parent_table = :table AND parent_id = :id AND key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True),
        ),
        {"table": _EPISODES, "id": episode.id, "keys": list(_NO_USABLE_MEDIA_KEYS)},
    )


def _delete_unusable_episode(connection, episode_id: int) -> None:
    connection.execute(
        sa.text("DELETE FROM metadata WHERE parent_table = :table AND parent_id = :id"),
        {"table": _EPISODES, "id": episode_id},
    )
    connection.execute(sa.text(f"DELETE FROM {_EPISODES} WHERE id = :id"), {"id": episode_id})
    connection.execute(sa.text("DELETE FROM media_items WHERE id = :id"), {"id": episode_id})


# Retention.

def _upgrade_retention() -> None:
    """A Download Profile that deletes older episodes can also delete the manual downloads of its collection in its
    Local Media Profile. Media a Site removes itself after a while counts as removed by the Site's retention from a
    time on."""
    op.add_column("download_profiles", sa.Column(
        "retention_includes_manual", sa.Boolean(), nullable=False, server_default="0",
        comment="Whether deleting older episodes also deletes the manual downloads of the collection in its Local Media Profile",
    ))
    op.add_column("media_items", sa.Column(
        "retention_due_at", sa.DateTime(timezone=True), nullable=True,
        comment=(
            "While the Source no longer has the media: from when its Site's retention may have removed it, the least "
            "time the Site keeps media after publication, less a little leeway"
        ),
    ))


def _downgrade_retention() -> None:
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("retention_due_at")
    with op.batch_alter_table("download_profiles") as batch:
        batch.drop_column("retention_includes_manual")


# Sites in order.

# As the Sources named them when this migration was written.
_ALWAYS_LISTED = (
    {"key": "dailywire", "name": "The Daily Wire", "domains": ["dailywire.com"]},
    {"key": "npo", "name": "NPO Start", "domains": ["npo.nl"]},
    {"key": "youtube", "name": "YouTube", "domains": ["youtube.com"]},
)
_SITES = sa.table(
    "sites", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("domains", sa.JSON),
    sa.column("position", sa.Integer),
)


def _upgrade_sites_in_order() -> None:
    """Every list of Sites shows them in the order they were added, so each Site gets a position; the Sites an
    installation already has are numbered by name. The Daily Wire, NPO Start and YouTube, which VODLoft used to list
    without a row, become ordinary Site rows, so the user can remove them like any other Site."""
    op.add_column("sites", sa.Column(
        "position", sa.Integer(), nullable=False, server_default="0",
        comment="Where the Site comes in lists of Sites: the order VODLoft got them in",
    ))
    bind = op.get_bind()
    existing = set(bind.execute(sa.select(_SITES.c.key)).scalars())
    missing = [site for site in _ALWAYS_LISTED if site["key"] not in existing]
    if missing:
        op.bulk_insert(_SITES, missing)
    keys = bind.execute(sa.select(_SITES.c.key).order_by(sa.func.lower(_SITES.c.name), _SITES.c.key)).scalars().all()
    for position, key in enumerate(keys, start=1):
        bind.execute(sa.update(_SITES).where(_SITES.c.key == key).values(position=position))


def _downgrade_sites_in_order() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("position")


# The note that asks for an API key.

def _upgrade_api_key_note() -> None:
    """The note on Home that asks for an API key can be put off or turned off."""
    op.add_column("settings", sa.Column(
        "api_key_note_after", sa.DateTime(timezone=True), nullable=True,
        comment="Until when Home does not ask for an API key, after Remind me later",
    ))
    op.add_column("settings", sa.Column(
        "api_key_note_off", sa.Boolean(), nullable=False, server_default=sa.false(),
        comment="Home never asks for an API key",
    ))


def _downgrade_api_key_note() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("api_key_note_off")
        batch.drop_column("api_key_note_after")


# The new lists rule.

def _upgrade_new_lists_rule() -> None:
    """Installations that have their notification rules already get the new default one: a channel collection's new
    lists, pushed to administrators. A new database gets it with the other defaults from the initial seed."""
    bind = op.get_bind()
    present = bind.execute(
        sa.text("SELECT default_key FROM notification_rules WHERE personal = :personal"), {"personal": False},
    ).scalars().all()
    if not present or "new_lists_found" in present:
        return
    position = bind.execute(
        sa.text("SELECT MAX(position) FROM notification_rules WHERE personal = :personal"), {"personal": False},
    ).scalar()
    rules = sa.table(
        "notification_rules",
        sa.column("position", sa.Integer), sa.column("personal", sa.Boolean), sa.column("default_key", sa.String),
        sa.column("enabled", sa.Boolean), sa.column("event", sa.String), sa.column("collection_scope", sa.String),
        sa.column("collection_ids", sa.JSON), sa.column("push", sa.Boolean), sa.column("destination_ids", sa.JSON),
        sa.column("delivery", sa.String), sa.column("summary_time", sa.String),
    )
    op.bulk_insert(rules, [{
        "position": (position or 0) + 1, "personal": False, "default_key": "new_lists_found", "enabled": True,
        "event": "new_lists_found", "collection_scope": "any", "collection_ids": [], "push": True,
        "destination_ids": [], "delivery": "now", "summary_time": "08:00",
    }])


def _downgrade_new_lists_rule() -> None:
    op.execute(sa.text("DELETE FROM notification_events WHERE event = 'new_lists_found'"))
    op.execute(sa.text("DELETE FROM notification_rules WHERE event = 'new_lists_found'"))


# Where each season came from.

# The Sources that had seasons of their own when this migration was written.
_OWN_SEASON_SOURCES = ("dailywire", "npo")
# A season per year is known by its slug, its four-digit year.
_NOT_A_YEAR = "NOT (length(s.slug) = 4 AND s.slug NOT GLOB '*[^0-9]*')"
_NOT_A_YEAR_PG = "NOT (s.slug ~ '^[0-9]{4}$')"


def _upgrade_season_origin() -> None:
    """Each season knows where it came from: its Site's own, one of the Site's lists, or made by VODLoft. On The Daily
    Wire and NPO Start, whose Sources have seasons of their own, a season that is not a season per year came from the
    Site; every other season VODLoft made. The background migration that tells collections of one list apart gives
    their season the list as its origin."""
    op.add_column("seasons", sa.Column(
        "origin", sa.String(), nullable=False, server_default="vodloft",
        comment="Where the season came from: the Site's own (site), one of its lists (list), or made by VODLoft (vodloft)",
    ))
    bind = op.get_bind()
    not_a_year = _NOT_A_YEAR_PG if bind.dialect.name == "postgresql" else _NOT_A_YEAR
    bind.execute(
        sa.text(
            "UPDATE seasons SET origin = 'site' WHERE id IN (SELECT s.id FROM seasons s "
            f"JOIN collections c ON c.id = s.collection_id WHERE c.source_key IN :sources AND {not_a_year})"
        ).bindparams(sa.bindparam("sources", expanding=True)),
        {"sources": list(_OWN_SEASON_SOURCES)},
    )


def _downgrade_season_origin() -> None:
    with op.batch_alter_table("seasons") as batch:
        batch.drop_column("origin")
