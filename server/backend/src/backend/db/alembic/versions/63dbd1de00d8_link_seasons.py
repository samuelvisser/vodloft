"""Link seasons instead of collections with several links.

A collection has one link again. A collection made from a channel can make the channel's playlists, or an artist's
albums, seasons: link seasons, each a link whose videos go to its season. The playlist and album links a collection
had become those, with the season and the videos each one had. The user can put a
collection's seasons in their own order.

Revision ID: 63dbd1de00d8
Revises: 34b2dd5c2fe8
Create Date: 2026-11-18
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa
from alembic import op


revision = "63dbd1de00d8"
down_revision = "34b2dd5c2fe8"
branch_labels = None
depends_on = None


def _playlist_id(url: str) -> str | None:
    found = parse_qs(urlsplit(url).query).get("list")
    return found[0] if found else None


def _artist_page(url: str) -> str | None:
    """The page of all music of the Bandcamp or SoundCloud artist an album link belongs to."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith(".bandcamp.com") and host.count(".") == 2 and "/album/" in parts.path:
        return f"https://{host}"
    if host in {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"} and "/sets/" in parts.path:
        artist = next((part for part in parts.path.split("/") if part), "")
        return f"https://soundcloud.com/{artist}/tracks" if artist else None
    return None


def upgrade() -> None:
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column(
            "link_seasons", sa.String(), nullable=False, server_default="off",
            comment="Whether the channel's playlists are seasons: off, all or selected",
        ))
        batch.add_column(sa.Column(
            "new_link_seasons", sa.String(), nullable=False, server_default="ask",
            comment="What happens with a playlist the channel adds, when only selected playlists are seasons: ask, add or ignore",
        ))
        batch.add_column(sa.Column(
            "loose_videos", sa.String(), nullable=False, server_default="one_season",
            comment="Where the videos in none of the playlists that are seasons go: one_season or by_year",
        ))
        batch.add_column(sa.Column(
            "outside_videos", sa.String(), nullable=False, server_default="leave_out",
            comment="What happens with the videos of the playlists that are seasons that the collection's own link does not list: leave_out or add",
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
    op.create_table(
        "link_seasons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id", sa.Integer(),
            sa.ForeignKey("collections.id", name="fk_link_seasons_collection_id_collections", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref", sa.String(), nullable=False, comment="The Site's own id for the playlist"),
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
            "season_id", sa.Integer(),
            sa.ForeignKey("seasons.id", name="fk_link_seasons_season_id_seasons", ondelete="SET NULL"),
            nullable=True, comment="The playlist's season, once it has one",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_link_seasons"),
        sa.UniqueConstraint("collection_id", "ref", name="uq_link_season_ref"),
    )
    op.create_index("ix_link_seasons_collection_id", "link_seasons", ["collection_id"])
    op.create_table(
        "link_season_items",
        sa.Column(
            "link_season_id", sa.Integer(),
            sa.ForeignKey(
                "link_seasons.id", name="fk_link_season_items_link_season_id_link_seasons",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0",
            comment="Where the playlist lists the video, from 0: its order at its Site",
        ),
        sa.PrimaryKeyConstraint("link_season_id", "source_slug", name="pk_link_season_items"),
    )

    # A playlist that was one season of a collection becomes one of its playlist seasons, and an album that was one
    # season of an artist's collection one of its album seasons, with the artist's page as the collection's link.
    # The old links did not keep their videos' order, so the next look at the Site gives each video its place.
    bind = op.get_bind()
    links = bind.execute(sa.text(
        "SELECT collection_links.id, collection_links.collection_id, collection_links.url, collection_links.title,"
        " collection_links.season_id, collection_links.position, collections.sharing_url FROM collection_links"
        " JOIN collections ON collections.id = collection_links.collection_id"
        " WHERE collection_links.placement = 'one_season'"
        " ORDER BY collection_links.collection_id, collection_links.position, collection_links.id"
    )).fetchall()
    with_playlists: dict[int, str | None] = {}
    for link_id, collection_id, url, title, season_id, position, sharing_url in links:
        artist = _artist_page(url)
        if artist is not None:
            ref = urlsplit(url).path.strip("/")
        elif url != sharing_url:
            ref = _playlist_id(url)
        else:
            ref = None
        if not ref:
            continue
        playlist_id = bind.execute(sa.text(
            "INSERT INTO link_seasons (collection_id, ref, url, title, site_position, enabled, status, season_id)"
            " VALUES (:collection_id, :ref, :url, :title, :position, :enabled, 'known', :season_id) RETURNING id"
        ), {
            "collection_id": collection_id, "ref": ref, "url": url, "title": title or ref, "position": position,
            "enabled": True, "season_id": season_id,
        }).scalar_one()
        bind.execute(sa.text(
            "INSERT INTO link_season_items (link_season_id, source_slug)"
            " SELECT :playlist_id, source_slug FROM collection_link_items WHERE link_id = :link_id"
        ), {"playlist_id": playlist_id, "link_id": link_id})
        with_playlists.setdefault(collection_id, artist)
    for collection_id, artist in with_playlists.items():
        bind.execute(
            sa.text("UPDATE collections SET link_seasons = 'selected' WHERE id = :id"), {"id": collection_id},
        )
        if artist is not None:
            bind.execute(
                sa.text("UPDATE collections SET sharing_url = :url WHERE id = :id"), {"url": artist, "id": collection_id},
            )

    # Videos no longer move between a channel's collections, so the task that did is gone.
    bind.execute(sa.text("DELETE FROM task_operation_targets WHERE task_key = 'reclaim_channel_videos'"))
    for table in ("task_runs", "task_schedules"):
        bind.execute(sa.text(
            f"DELETE FROM {table} WHERE definition_id IN (SELECT id FROM task_definitions WHERE key = 'reclaim_channel_videos')"
        ))
    bind.execute(sa.text("DELETE FROM task_definitions WHERE key = 'reclaim_channel_videos'"))

    with op.batch_alter_table("media_items_episode") as batch:
        batch.add_column(sa.Column(
            "from_link_season", sa.Boolean(), nullable=False, server_default="0",
            comment="Added because a playlist that is a season lists it, not the collection's own link",
        ))
        batch.drop_index("ix_media_items_episode_collection_link_id")
        batch.drop_constraint("fk_media_items_episode_collection_link_id_collection_links", type_="foreignkey")
        batch.drop_column("collection_link_id")
    op.drop_table("collection_link_items")
    op.drop_index("ix_collection_links_collection_id", table_name="collection_links")
    op.drop_table("collection_links")


def downgrade() -> None:
    op.create_table(
        "collection_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "collection_id", sa.Integer(),
            sa.ForeignKey("collections.id", name="fk_collection_links_collection_id_collections", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("placement", sa.String(), nullable=False, server_default="site_seasons"),
        sa.Column(
            "channel_section_id", sa.Integer(),
            sa.ForeignKey("channel_sections.id", name="fk_collection_links_channel_section_id_channel_sections", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "season_id", sa.Integer(),
            sa.ForeignKey("seasons.id", name="fk_collection_links_season_id_seasons", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_collection_links"),
        sa.UniqueConstraint("collection_id", "url", name="uq_collection_link_url"),
        sa.UniqueConstraint("channel_section_id", name="uq_collection_links_channel_section_id"),
    )
    op.create_index("ix_collection_links_collection_id", "collection_links", ["collection_id"])
    op.create_table(
        "collection_link_items",
        sa.Column(
            "link_id", sa.Integer(),
            sa.ForeignKey("collection_links.id", name="fk_collection_link_items_link_id_collection_links", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_slug", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("link_id", "source_slug", name="pk_collection_link_items"),
    )
    with op.batch_alter_table("media_items_episode") as batch:
        batch.drop_column("from_link_season")
        batch.add_column(sa.Column("collection_link_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_media_items_episode_collection_link_id_collection_links", "collection_links",
            ["collection_link_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_media_items_episode_collection_link_id", ["collection_link_id"])
    op.execute(
        "INSERT INTO collection_links (collection_id, url, position, placement) "
        "SELECT id, sharing_url, 0, 'site_seasons' FROM collections"
    )
    op.drop_table("link_season_items")
    op.drop_index("ix_link_seasons_collection_id", table_name="link_seasons")
    op.drop_table("link_seasons")
    with op.batch_alter_table("seasons") as batch:
        batch.drop_column("loose")
    with op.batch_alter_table("collections") as batch:
        batch.drop_column("custom_season_order")
        batch.drop_column("outside_videos")
        batch.drop_column("loose_videos")
        batch.drop_column("new_link_seasons")
        batch.drop_column("link_seasons")
