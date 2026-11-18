"""WebDAV stream profiles: a read-only share laid out as a TV show, with NFO files and artwork."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pytest
from conftest import available_artifact
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

DAV = "{DAV:}"


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    # The share's routes run in another thread than the test.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    session = Session(engine)
    Base.metadata.create_all(engine)
    yield session
    session.close()
    engine.dispose()


def _collection(session, slug="show", identifier="numbered"):
    from backend.db.models import Collection, Season

    collection = Collection(
        source_key="dailywire", uuid=f"{slug}-uuid", slug=slug, title=f"The {slug.title()}", description="About",
        sharing_url=f"https://www.dailywire.com/{slug}", membership_level="FREE", type="podcast",
        episode_identifier=identifier, author_name="Host", author_slug="host",
        thumbnail_portrait_path=f"https://images.test/{slug}-poster.jpg",
    )
    session.add(collection)
    session.add(Season(collection=collection, index=1, slug=f"{slug}-season", name="Season 1", season_number=1))
    session.flush()
    return collection


def _episode(session, collection, number, *, at):
    from backend.db.models import Episode

    episode = Episode(
        source_key="dailywire", uuid=f"{collection.slug}-{number}", type="episode", collection=collection,
        season=collection.seasons[0], index=number, episode_identifier=f"ep.{number}",
        slug=f"{collection.slug}-{number}", title=f"Episode {number}: A/B", description="What happens",
        duration=1800.0, publish_status="published_final", sharing_url=f"https://www.dailywire.com/{number}",
        published_date=at, thumbnail_landscape_path=f"https://images.test/{number}.jpg",
    )
    session.add(episode)
    session.flush()
    return episode


def _download(session, episode, tmp_path, *, preferred_format="format_1080p", suffix=".mp4"):
    from backend.db.models import EpisodeMediaDownload, LocalMediaProfile

    local = session.query(LocalMediaProfile).filter_by(slug=preferred_format).one_or_none()
    if local is None:
        local = LocalMediaProfile(
            slug=preferred_format, name=preferred_format, preferred_format=preferred_format,
            output_template="/downloads/{{ episode_title }}.ext",
        )
        session.add(local)
        session.flush()
    path = tmp_path / f"{episode.slug}{suffix}"
    path.write_bytes(b"0123456789")
    session.add(EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=local.id, file_path=str(path),
        **available_artifact(), downloaded_bytes=10, downloaded_at=datetime.now(timezone.utc),
        downloaded_publish_status=episode.publish_status,
    ))
    session.flush()
    return path


def _share(session, collection, *, token=None, **values):
    from backend.db.models import WebdavStreamProfile

    profile = WebdavStreamProfile(
        collection=collection, enable_profile=True, token=token or f"{collection.slug}-token",
        use_downloads=values.pop("use_downloads", True), use_source_stream=values.pop("use_source_stream", False),
        preferred_format=values.pop("preferred_format", "format_1080p"),
        prefer_exact_match=False, ep_id_type_list=["ep"], stream_live_episodes=False, **values,
    )
    session.add(profile)
    session.flush()
    return profile


def _tree(node, prefix=""):
    from backend.services.webdav import ShareFolder

    lines = []
    for name, child in sorted(node.children.items()):
        if isinstance(child, ShareFolder):
            lines.append(f"{prefix}{name}/")
            lines += _tree(child, f"{prefix}{name}/")
        else:
            lines.append(f"{prefix}{name}")
    return lines


def test_a_show_has_season_folders_with_its_downloaded_episodes_nfo_files_and_artwork(db_session, tmp_path):
    from backend.services.webdav import show_folder

    collection = _collection(db_session)
    for number in (1, 2):
        _download(db_session, _episode(db_session, collection, number, at=datetime(2026, 3, number, tzinfo=timezone.utc)), tmp_path)
    _episode(db_session, collection, 3, at=datetime(2026, 3, 3, tzinfo=timezone.utc))
    profile = _share(db_session, collection)

    assert _tree(show_folder(db_session, profile)) == [
        "Season 01/",
        "Season 01/The Show - S01E01 - Episode 1： A⧸B-thumb.jpg",
        "Season 01/The Show - S01E01 - Episode 1： A⧸B.mp4",
        "Season 01/The Show - S01E01 - Episode 1： A⧸B.nfo",
        "Season 01/The Show - S01E02 - Episode 2： A⧸B-thumb.jpg",
        "Season 01/The Show - S01E02 - Episode 2： A⧸B.mp4",
        "Season 01/The Show - S01E02 - Episode 2： A⧸B.nfo",
        "Season 01/season.nfo",
        "poster.jpg",
        "tvshow.nfo",
    ]


def test_a_show_by_year_names_episodes_by_date_and_can_leave_out_metadata(db_session, tmp_path):
    from backend.services.webdav import show_folder

    collection = _collection(db_session)
    _download(db_session, _episode(db_session, collection, 1, at=datetime(2025, 12, 31, tzinfo=timezone.utc)), tmp_path)
    _download(db_session, _episode(db_session, collection, 2, at=datetime(2026, 1, 2, tzinfo=timezone.utc)), tmp_path)
    profile = _share(db_session, collection, overwrite_collection_title="News", season_folders="year", metadata_files="none")

    assert _tree(show_folder(db_session, profile)) == [
        "Season 2025/",
        "Season 2025/News - 2025-12-31 - Episode 1： A⧸B.mp4",
        "Season 2026/",
        "Season 2026/News - 2026-01-02 - Episode 2： A⧸B.mp4",
    ]


def test_an_audio_share_lists_audio_files_in_one_folder_with_artwork_only(db_session, tmp_path):
    from backend.services.webdav import show_folder

    collection = _collection(db_session)
    episode = _episode(db_session, collection, 1, at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    _download(db_session, episode, tmp_path)
    _download(db_session, episode, tmp_path, preferred_format="format_audio_only", suffix=".m4a")
    profile = _share(
        db_session, collection, preferred_format="format_audio_only", season_folders="none", metadata_files="artwork",
    )

    assert _tree(show_folder(db_session, profile)) == [
        "The Show - 2026-03-01 - Episode 1： A⧸B-thumb.jpg",
        "The Show - 2026-03-01 - Episode 1： A⧸B.m4a",
        "poster.jpg",
    ]


def test_a_share_that_streams_from_the_site_lists_episodes_in_the_stream_video_cache(db_session, tmp_path, monkeypatch):
    from backend.services import webdav

    collection = _collection(db_session)
    _episode(db_session, collection, 1, at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    _episode(db_session, collection, 2, at=datetime(2026, 3, 2, tzinfo=timezone.utc))
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"cached")
    monkeypatch.setattr(webdav, "get_cached_mp4_path", lambda key: cached if key == "show-2" else None)
    profile = _share(db_session, collection, use_downloads=False, use_source_stream=True, metadata_files="none")

    assert _tree(webdav.show_folder(db_session, profile)) == [
        "Season 01/", "Season 01/The Show - S01E02 - Episode 2： A⧸B.mp4",
    ]


def test_a_user_token_opens_all_their_shows_and_names_that_clash_are_numbered(db_session, tmp_path):
    from backend.db.models.user import User
    from backend.services.webdav import ShareFile, find, shows_for_token

    owner = User(username="owner", password_hash="x", stream_token="owner-token")
    db_session.add(owner)
    db_session.flush()
    first = _share(db_session, _collection(db_session, "first"), owner_user_id=owner.id, overwrite_collection_title="Show")
    second = _share(db_session, _collection(db_session, "second"), owner_user_id=owner.id, overwrite_collection_title="Show")
    _download(db_session, _episode(db_session, second.collection, 1, at=datetime(2026, 3, 1, tzinfo=timezone.utc)), tmp_path)

    shows = shows_for_token(db_session, "owner-token")

    assert shows == [first, second]
    assert sorted(find(db_session, shows, []).children) == ["Show", "Show (2)"]
    assert shows_for_token(db_session, "first-token") == [first]
    found = find(db_session, shows, ["show (2)", "season 01", "show - s01e01 - episode 1： a⧸b.mp4"])
    assert isinstance(found, ShareFile) and found.path.read_bytes() == b"0123456789"
    assert find(db_session, shows, ["Show", "Missing"]) is None


def test_propfind_lists_a_folder_and_what_it_holds(db_session, tmp_path):
    from backend.api.endpoints.webdav.service import render_propfind
    from backend.services.webdav import show_folder

    collection = _collection(db_session)
    _download(db_session, _episode(db_session, collection, 1, at=datetime(2026, 3, 1, tzinfo=timezone.utc)), tmp_path)
    folder = show_folder(db_session, _share(db_session, collection, metadata_files="none"))

    multistatus = ET.fromstring(render_propfind("/webdav/t", ["The Show"], folder, depth=1))

    responses = {response.findtext(f"{DAV}href"): response for response in multistatus}
    assert list(responses) == ["/webdav/t/The%20Show/", "/webdav/t/The%20Show/Season%2001/"]
    assert responses["/webdav/t/The%20Show/"].find(f".//{DAV}resourcetype/{DAV}collection") is not None
    season = folder.children["Season 01"]
    file_name = next(iter(season.children))
    file = ET.fromstring(render_propfind("/webdav/t", ["The Show", "Season 01", file_name], season.children[file_name], depth=1))
    assert len(file) == 1
    assert file.findtext(f".//{DAV}getcontentlength") == "10"
    assert file.findtext(f".//{DAV}getcontenttype") == "video/mp4"


def test_the_share_answers_webdav_reads_with_byte_ranges_and_refuses_changes(db_session, tmp_path, monkeypatch):
    from fastapi import Response

    from backend.api.endpoints.webdav import router as webdav
    from backend.services.errors import ServiceError

    collection = _collection(db_session)
    _download(db_session, _episode(db_session, collection, 1, at=datetime(2026, 3, 1, tzinfo=timezone.utc)), tmp_path)
    _share(db_session, collection)

    @contextmanager
    def session():
        yield db_session

    monkeypatch.setattr(webdav, "db_session", session)
    app = FastAPI()
    app.include_router(webdav.router)
    # As VODLoft's app answers a refusal of a service.
    app.add_exception_handler(ServiceError, lambda _request, error: Response(status_code=error.status_code))
    file_url = "/webdav/show-token/The%20Show/Season%2001/The%20Show%20-%20S01E01%20-%20Episode%201%EF%BC%9A%20A%E2%A7%B8B.mp4"
    with TestClient(app) as client:
        options = client.options("/webdav/show-token/")
        assert options.headers["DAV"] == "1"
        listing = client.request("PROPFIND", "/webdav/show-token/", headers={"Depth": "1"})
        assert listing.status_code == 207
        assert "/webdav/show-token/The%20Show/" in listing.text
        part = client.get(file_url, headers={"Range": "bytes=2-5"})
        assert (part.status_code, part.content) == (206, b"2345")
        nfo = client.get("/webdav/show-token/The%20Show/tvshow.nfo")
        assert nfo.status_code == 200 and b"<tvshow>" in nfo.content
        assert client.put(file_url, content=b"x").status_code == 405
        assert client.request("PROPFIND", "/webdav/unknown/").status_code == 404
