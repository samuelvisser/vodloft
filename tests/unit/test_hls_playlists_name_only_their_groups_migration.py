"""The playlists of Daily Wire HLS downloads stop naming the subtitle group they do not keep, which
Apple's players refuse, and their downloads remember the rewritten file."""
from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import available_artifact, use_database

MIGRATION = "backend.db.background_migrations.versions.17506d02e509_hls_playlists_name_only_their_groups"

DAILY_WIRE = """#EXTM3U
#EXT-X-VERSION:5
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=998800,CODECS="mp4a.40.2,avc1.64001f",RESOLUTION=854x480,CLOSED-CAPTIONS=NONE,SUBTITLES="sub1"
hls/480p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2016300,CODECS="mp4a.40.2,avc1.640020",RESOLUTION=1280x720,CLOSED-CAPTIONS=NONE,SUBTITLES="sub1"
hls/720p/playlist.m3u8
"""
YOUTUBE = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Audio",DEFAULT=YES,AUTOSELECT=YES,URI="hls/audio-0/playlist.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=339000,RESOLUTION=640x360,AUDIO="audio"
hls/360p/playlist.m3u8
"""


class _Context:
    def raise_if_canceled(self):
        return None

    def update_progress(self, current, total, message=None):
        return None


@pytest.fixture
def factory():
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    yield sessionmaker(engine)
    engine.dispose()


def _downloads(session, paths) -> list[int]:
    from backend.db.models import Collection, Episode, LocalMediaProfile, Season
    from backend.db.models.media_download import EpisodeMediaDownload

    local = LocalMediaProfile(slug="hls", name="HLS", preferred_format="format_hls", output_template="/x/{{ episode }}.ext")
    collection = Collection(
        source_key="dailywire", uuid="show", slug="show", title="Show", description=None,
        sharing_url="https://www.dailywire.com/show/show", membership_level="FREE", type="series",
        episode_identifier="numbered", author_name="A", author_slug="a",
    )
    season = Season(collection=collection, index=1, slug="show-1", name="One")
    session.add_all([local, collection, season])
    session.flush()
    ids = []
    for index, path in enumerate(paths, start=1):
        episode = Episode(
            source_key="dailywire", uuid=str(path), type="episode", collection=collection, season=season, index=index,
            episode_identifier=f"ep.{index}", slug=f"ep-{index}", title=str(index), publish_status="published_final",
            sharing_url=f"https://www.dailywire.com/episode/{index}",
        )
        session.add(episode)
        session.flush()
        download = EpisodeMediaDownload(
            type="episode", media_item_id=episode.id, local_media_profile_id=local.id, file_path=str(path),
            **available_artifact(),
        )
        session.add(download)
        session.flush()
        ids.append(download.id)
    session.commit()
    return ids


def test_playlists_stop_naming_groups_they_do_not_define(factory, monkeypatch, tmp_path):
    from backend.db.models.media_download import EpisodeMediaDownload

    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    daily_wire, youtube = tmp_path / "daily-wire.m3u8", tmp_path / "youtube.m3u8"
    daily_wire.write_text(DAILY_WIRE)
    youtube.write_text(YOUTUBE)
    with factory() as session:
        daily_wire_id, youtube_id = _downloads(session, [daily_wire, youtube])

    asyncio.run(module.migrate(_Context()))

    assert daily_wire.read_text() == DAILY_WIRE.replace(',SUBTITLES="sub1"', "")
    assert youtube.read_text() == YOUTUBE  # Its audio group is defined.
    with factory() as session:
        download = session.get(EpisodeMediaDownload, daily_wire_id)
        assert download.artifact_size_bytes == daily_wire.stat().st_size
        assert download.artifact_stat_ino == str(daily_wire.stat().st_ino)

    # Running it again changes nothing.
    asyncio.run(module.migrate(_Context()))
    assert daily_wire.read_text() == DAILY_WIRE.replace(',SUBTITLES="sub1"', "")
