"""Downloads made before VODLoft remembered their length get it from their files, and a Daily Wire
episode cut down before the update is checked right away."""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import available_artifact, use_database

MIGRATION = "backend.db.background_migrations.versions.e8ea12937f41_download_lengths"
LENGTHS = {"/dw/cut.mkv": 7 * 3600.0, "/dw/old.mkv": 3600.0, "/yt/video.mkv": 600.0}


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


def _downloads(session) -> dict[str, int]:
    """A Daily Wire episode now listed at 3.5 hours, downloaded today at 7 hours; an old Daily Wire
    episode with its length unchanged; and a YouTube video. Returns each download's id by file."""
    from backend.db.models import Collection, Episode, LocalMediaProfile, Season
    from backend.db.models.download_profile import DownloadProfile
    from backend.db.models.media_download import EpisodeMediaDownload

    now = datetime.now(timezone.utc)
    local = LocalMediaProfile(slug="shows", name="Shows", preferred_format="format_1080p", output_template="/x/{{ episode }}.ext")
    session.add(local)
    found = {}
    for source_key, url, files in (
        ("dailywire", "https://www.dailywire.com/show/election-wire", (("/dw/cut.mkv", 3.5 * 3600, now), ("/dw/old.mkv", 3600, now - timedelta(days=90)))),
        ("ytdlp", "https://www.youtube.com/@channel", (("/yt/video.mkv", 600, now),)),
    ):
        collection = Collection(
            source_key=source_key, uuid=source_key, slug=source_key, title=source_key, description=None, sharing_url=url,
            membership_level="FREE", type="series", episode_identifier="numbered", author_name="A", author_slug="a",
        )
        season = Season(collection=collection, index=1, slug=f"{source_key}-1", name="One")
        profile = DownloadProfile(
            collection=collection, local_media_profile=local, enable_profile=True, upgrade_check=True,
            upgrade_improvements=["length"] if source_key == "dailywire" else ["resolution"],
        )
        session.add_all([collection, season, profile])
        session.flush()
        for index, (path, listed, downloaded_at) in enumerate(files, start=1):
            episode = Episode(
                source_key=source_key, uuid=path, type="episode", collection=collection, season=season, index=index,
                episode_identifier=f"ep.{index}", slug=path, title=path, publish_status="published_final",
                sharing_url=f"{url}/{index}", duration=listed,
            )
            session.add(episode)
            session.flush()
            download = EpisodeMediaDownload(
                type="episode", media_item_id=episode.id, local_media_profile_id=local.id, download_profile_id=profile.id,
                file_path=path, downloaded_at=downloaded_at, **available_artifact(),
            )
            session.add(download)
            session.flush()
            found[path] = download.id
    session.commit()
    return found


def test_downloads_get_their_length_and_a_cut_down_episode_its_check(factory, monkeypatch):
    from backend.db.models.media_download import EpisodeMediaDownload

    module = importlib.import_module(MIGRATION)
    monkeypatch.setattr(module, "get_session", factory)
    monkeypatch.setattr(module, "media_duration", lambda path, ffmpeg_path: LENGTHS.get(path))
    with factory() as session:
        ids = _downloads(session)

    asyncio.run(module.migrate(_Context()))

    with factory() as session:
        downloads = {path: session.get(EpisodeMediaDownload, download_id) for path, download_id in ids.items()}
        assert {path: download.duration for path, download in downloads.items()} == LENGTHS
        # The cut-down Daily Wire episode is checked now; the old one with an unchanged length and the
        # YouTube video, whose profile does not check for a different length, are not.
        assert downloads["/dw/cut.mkv"].upgrade_check_at is not None
        assert downloads["/dw/old.mkv"].upgrade_check_at is None
        assert downloads["/yt/video.mkv"].upgrade_check_at is None
