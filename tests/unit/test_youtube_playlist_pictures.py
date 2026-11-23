"""A YouTube playlist's own picture stops working within a day, so a playlist takes its first video's still."""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest
from conftest import use_database
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

MIGRATION = "backend.db.background_migrations.versions.7aaaa88fe96d_lasting_link_pictures"
SIGNED = "https://i9.ytimg.com/s_p/PLseven/landscape_sddefault.jpg?sqp=CMiPk9gG&rs=AOn4"
UNSIGNED = "https://i9.ytimg.com/s_p/PLseven/maxresdefault.jpg"
STILL = "https://i.ytimg.com/vi/nrU8Kh6Mf7o/hqdefault.jpg?sqp=-oay"


def test_a_playlist_takes_its_first_videos_still_over_its_own_picture():
    from sources.ytdlp.site_implementations.youtube import picture

    playlist = {"thumbnails": [{"url": UNSIGNED}, {"url": SIGNED}], "entries": [{"thumbnails": [{"url": STILL}]}]}
    assert picture(playlist) == STILL
    # Without its videos, its own picture is all there is.
    assert picture({"thumbnails": [{"url": UNSIGNED}, {"url": SIGNED}]}) == SIGNED
    assert picture({"thumbnails": [{"url": UNSIGNED}]}) is None
    assert picture({"thumbnail": STILL}) == STILL


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
