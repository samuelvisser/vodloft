"""YouTube lists a playlist's own picture in sizes it never made, so a playlist takes one YouTube serves."""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from conftest import use_database
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

MIGRATION = "backend.db.background_migrations.versions.9c25f5b4d4d1_served_link_pictures"
SIGNED = "https://i9.ytimg.com/s_p/PLseven/landscape_sddefault.jpg?sqp=CMiPk9gG&rs=AOn4"
UNSIGNED = "https://i9.ytimg.com/s_p/PLseven/maxresdefault.jpg"
STILL = "https://i.ytimg.com/vi/nrU8Kh6Mf7o/hqdefault.jpg?sqp=-oay"


MAXRES = "https://i9.ytimg.com/s_p/PLseven/landscape_maxresdefault.jpg?sqp=CPyfk9gG&rs=AOn4"


def _serves(monkeypatch, *missing):
    """YouTube answers these pictures with its grey placeholder and HTTP 404."""
    from sources.ytdlp import thumbnails

    monkeypatch.setattr(thumbnails, "served", lambda url: bool(url) and url not in missing)
    monkeypatch.setattr(thumbnails, "widest_still", lambda url: url)


def test_a_playlist_takes_the_largest_of_its_own_pictures_youtube_serves(monkeypatch):
    from sources.ytdlp.source import _thumbnail

    _serves(monkeypatch, MAXRES)
    entries = [{"thumbnails": [{"url": STILL}]}]
    assert _thumbnail({"thumbnails": [{"url": UNSIGNED}, {"url": SIGNED}, {"url": MAXRES}], "entries": entries}) == SIGNED
    # With none it serves, the playlist's first video's still.
    _serves(monkeypatch, MAXRES, SIGNED)
    assert _thumbnail({"thumbnails": [{"url": SIGNED}, {"url": MAXRES}], "entries": entries}) == STILL
    assert _thumbnail({"thumbnails": [{"url": UNSIGNED}]}) is None


def test_a_playlist_from_the_youtube_api_takes_a_size_youtube_serves(monkeypatch):
    from sources.ytdlp.youtube_api import catalogue as catalogue_module
    from sources.ytdlp.youtube_api.mapping import YouTubeRef

    monkeypatch.setattr(catalogue_module, "first_served", lambda urls: next(url for url in urls if url != MAXRES))
    item = {"id": "PLseven", "snippet": {"title": "Season 7", "thumbnails": {
        "maxres": {"url": MAXRES}, "standard": {"url": SIGNED}, "default": {"url": STILL},
    }}}
    catalogue = catalogue_module.Catalogue.__new__(catalogue_module.Catalogue)
    monkeypatch.setattr(catalogue, "playlist", lambda ref: item, raising=False)
    details = catalogue.collection(YouTubeRef("playlist", "PLseven"), "https://www.youtube.com/playlist?list=PLseven")
    assert details.image_url == SIGNED


class _Context:
    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        return None


@pytest.fixture
def migration(monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    use_database(engine)
    factory = sessionmaker(engine)
    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    yield module, factory
    engine.dispose()


def test_links_with_a_playlists_own_picture_get_one_that_keeps_working(migration, monkeypatch):
    from backend.db.models import Collection, CollectionList
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    module, factory = migration
    with factory() as session:
        collection = Collection(
            source_key="ytdlp", uuid="c-uuid", slug="citation-needed", title="Citation Needed", sharing_url=None,
            membership_level="FREE", type=CollectionType.SERIES.value, episode_identifier=EpisodeIdentifier.SEASONAL.value,
            author_name="", author_slug="",
        )
        for position, (ref, image) in enumerate((("PLseven", SIGNED), ("PLeight", STILL), ("PLgone", SIGNED))):
            collection.lists.append(CollectionList(
                ref=ref, url=f"https://www.youtube.com/playlist?list={ref}", title=ref, image_path=image,
                source_key="ytdlp", site_position=position, enabled=True,
            ))
        session.add(collection)
        session.commit()
    looked_up = []

    def collection_details(url):
        looked_up.append(url)
        if url.endswith("PLgone"):
            raise RuntimeError("The playlist does not exist")
        return SimpleNamespace(image_url="https://i.ytimg.com/vi/nrU8Kh6Mf7o/maxresdefault.jpg")

    monkeypatch.setattr(module, "get_source", lambda key: SimpleNamespace(collection_details=collection_details))
    asyncio.run(module.migrate(_Context()))

    with factory() as session:
        pictures = {link.ref: link.image_path for link in session.scalars(select(CollectionList))}
    assert pictures == {
        "PLseven": "https://i.ytimg.com/vi/nrU8Kh6Mf7o/maxresdefault.jpg",
        "PLeight": STILL,
        # One that can't be looked up keeps what it has.
        "PLgone": SIGNED,
    }
    assert len(looked_up) == 2
