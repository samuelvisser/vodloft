"""The three profile tables load 50 profiles at a time, with their filters applied by the server."""
from __future__ import annotations

import pytest
from conftest import available_artifact, use_database
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session():
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.db import Base

    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _collection(index: int, *, source_key: str = "dailywire", title: str | None = None):
    from backend.db.models import Collection
    from backend.types.collection_types import CollectionType, EpisodeIdentifier

    return Collection(
        source_key=source_key, site_key=source_key, uuid=f"collection-{index}", slug=f"show-{index}", title=title or f"Show {index:03d}",
        description=None, sharing_url=f"https://example.test/{index}", membership_level="FREE",
        type=CollectionType.PODCAST.value, episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host", author_slug="host",
    )


def _library(s: Session, count: int):
    """``count`` collections, each with an audio and a video Download Profile and a stream profile."""
    from backend.db.models import DownloadProfile, LocalMediaProfile, RssStreamProfile, Site

    audio = LocalMediaProfile(slug="audio", name="Audio", preferred_format="format_audio_only",
                              output_template="/downloads/audio/{{ episode }}.ext")
    video = LocalMediaProfile(slug="video", name="video files", preferred_format="format_1080p",
                              output_template="/downloads/video/{{ episode }}.ext", collection_scope="series")
    collections = [
        _collection(index, source_key="youtube" if index % 3 == 0 else "dailywire") for index in range(count)
    ]
    s.add_all([Site(key="dailywire", name="The Daily Wire", domains=[]), Site(key="youtube", name="YouTube", domains=[])])
    s.add_all([audio, video, *collections])
    s.flush()
    for index, collection in enumerate(collections):
        for profile in (audio, video):
            s.add(DownloadProfile(
                collection_id=collection.id, local_media_profile_id=profile.id, enable_profile=index % 2 == 0,
                download_with_countdown=False, redownload_final=False, delete_older_episodes=False,
            ))
        s.add(RssStreamProfile(
            collection_id=collection.id, enable_profile=True, use_downloads=index % 2 == 0,
            use_source_stream=index % 2 == 1, preferred_format="format_audio_only", prefer_exact_match=False,
            feed_url=f"https://example.test/feed/{index}",
        ))
    s.commit()
    return audio, video


def _all_pages(fetch):
    items, cursor, pages = [], None, 0
    while True:
        page = fetch(cursor)
        pages += 1
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items, page.total, pages


def test_download_profiles_page_through_every_profile_in_collection_title_order(session) -> None:
    from backend.api.endpoints.download_profiles.as_view.service import get_download_profile_views_page
    from backend.api.models.profile_list import DownloadProfileListQuery

    _library(session, 60)
    first = get_download_profile_views_page(session, DownloadProfileListQuery())
    assert len(first.items) == 50 and first.total == 120 and first.has_more

    items, total, pages = _all_pages(
        lambda cursor: get_download_profile_views_page(session, DownloadProfileListQuery(cursor=cursor))
    )
    assert pages == 3 and total == 120
    assert len({item.id for item in items}) == 120
    titles = [item.collection_title for item in items]
    assert titles == sorted(titles)


def test_download_profile_filters_narrow_the_page_and_its_total(session) -> None:
    from backend.api.endpoints.download_profiles.as_view.service import get_download_profile_views_page
    from backend.api.models.profile_list import DownloadProfileListQuery

    audio, _video = _library(session, 60)

    def total(**filters) -> int:
        page = get_download_profile_views_page(session, DownloadProfileListQuery(**filters, cursor=None, limit=50))
        return page.total

    assert total(format=["audio"]) == 60
    assert total(format=["audio", "video"]) == 120
    assert total(status=["disabled"]) == 60
    assert total(site=["youtube"]) == 40
    assert total(local_media_profile_id=audio.id) == 60
    assert total(search="show 045") == 2
    assert total(search="VIDEO 005") == 1
    # Search words are matched as text, not as LIKE patterns.
    assert total(search="%") == 0
    page = get_download_profile_views_page(
        session, DownloadProfileListQuery(site=["youtube"], status=["enabled"], cursor=None, limit=50))
    assert page.total == 20
    assert all(item.collection_source_key == "youtube" and item.enable_profile for item in page.items)


def test_a_cursor_only_continues_the_list_it_came_from(session) -> None:
    from backend.api.endpoints.download_profiles.as_view.service import get_download_profile_views_page
    from backend.api.models.profile_list import DownloadProfileListQuery

    _library(session, 30)
    page = get_download_profile_views_page(session, DownloadProfileListQuery(cursor=None, limit=10))
    with pytest.raises(HTTPException) as raised:
        get_download_profile_views_page(
            session, DownloadProfileListQuery(format=["audio"], cursor=page.next_cursor, limit=10))
    assert raised.value.status_code == 422
    with pytest.raises(HTTPException):
        get_download_profile_views_page(session, DownloadProfileListQuery(cursor="not-a-cursor", limit=10))


def test_stream_profiles_page_with_filters_and_owner_scope(session) -> None:
    from backend.api.endpoints.stream_profiles.as_view.service import get_stream_profile_views_page
    from backend.api.models.profile_list import StreamProfileListQuery
    from backend.security.access import Access

    _library(session, 70)
    access = Access.full()
    items, total, pages = _all_pages(
        lambda cursor: get_stream_profile_views_page(
            session, access, StreamProfileListQuery(cursor=cursor, limit=50))
    )
    assert (len(items), total, pages) == (70, 70, 2)
    assert items[0].collection_source_key in {"dailywire", "youtube"}

    def total_of(**filters) -> int:
        return get_stream_profile_views_page(
            session, access, StreamProfileListQuery(**filters, cursor=None, limit=50)).total

    assert total_of(streams_from=["downloads"]) == 35
    assert total_of(streams_from=["downloads", "source"]) == 70
    assert total_of(format=["video"]) == 0
    assert total_of(site=["youtube"]) == 24


def test_profile_tables_offer_the_sites_their_collections_are_on(session) -> None:
    from backend.api.endpoints.download_profiles.as_view.service import get_download_profile_sites
    from backend.api.endpoints.stream_profiles.as_view.service import get_stream_profile_sites
    from backend.db.models import Site
    from backend.security.access import Access

    _library(session, 6)
    session.add(Site(key="vimeo", name="Vimeo", domains=[]))
    session.commit()
    assert [site.name for site in get_download_profile_sites(session)] == ["The Daily Wire", "YouTube"]
    assert [site.key for site in get_stream_profile_sites(session, Access.full())] == ["dailywire", "youtube"]


def test_local_media_profiles_page_in_name_order_with_filters(session) -> None:
    from backend.api.endpoints.local_media_profiles.service import get_local_media_profile_views_page
    from backend.api.models.profile_list import LocalMediaProfileListQuery
    from backend.db.models import Episode, EpisodeMediaDownload, LocalMediaProfile, MovieLocalMediaProfile, Season
    from backend.types.media_types import MediaType

    profiles = [
        LocalMediaProfile(slug=f"profile-{index}", name=f"{'Zeta' if index % 2 else 'alpha'} {index:02d}",
                          preferred_format="format_1080p", output_template=f"/downloads/{index}/{{{{ episode }}}}.ext",
                          collection_scope="podcast", site_keys=["youtube"] if index % 5 == 0 else ["dailywire"])
        for index in range(55)
    ]
    movie = MovieLocalMediaProfile(slug="movies", name="Movies", preferred_format="format_audio_only",
                                   output_template="/downloads/movies/{{ title }}.ext", site_keys=["dailywire", "youtube"])
    collection = _collection(1)
    session.add_all([*profiles, movie, collection])
    session.flush()
    episode = Episode(
        source_key="dailywire", uuid="episode", type=MediaType.EPISODE.value, collection=collection,
        season=Season(collection=collection, index=1, slug="season-1", name="Season 1"),
        index=1, episode_identifier="ep1", slug="episode", title="Episode", description="", duration=60,
        publish_status="published_final", sharing_url="https://example.test/episode",
    )
    session.add(episode)
    session.flush()
    session.add(EpisodeMediaDownload(
        type=MediaType.EPISODE.value, media_item_id=episode.id, local_media_profile_id=profiles[3].id,
        file_path="/downloads/3/episode.mp4", **(available_artifact() | {"artifact_size_bytes": 10}),
    ))
    session.commit()

    def page(cursor=None, **filters):
        return get_local_media_profile_views_page(
            session, LocalMediaProfileListQuery(**filters, cursor=cursor, limit=50))

    items, total, pages = _all_pages(lambda cursor: page(cursor))
    assert (len(items), total, pages) == (56, 56, 2)
    names = [item.profile.name for item in items]
    assert names == sorted(names, key=str.lower)

    assert page(used_for=["movie"]).total == 1
    assert page(used_for=["podcast"]).total == 55
    assert page(used_for=["series"]).total == 0
    assert page(format=["audio"]).total == 1
    files = page(storage=["files"])
    assert [item.profile.id for item in files.items] == [profiles[3].id]
    assert files.items[0].statistics.storage_size_bytes == 10
    assert page(storage=["empty"]).total == 55
    assert page(search="zeta 0").total == 5
    assert page(search="downloads/movies").total == 1
    assert page(site=["youtube"]).total == 12
    assert page(site=["dailywire"]).total == 45
    assert page(site=["dailywire", "youtube"]).total == 56
    assert page(site=["vimeo"]).total == 0


def test_profile_table_endpoints_read_filters_from_the_query_string(session) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.download_profiles.router import router as download_profiles
    from backend.api.endpoints.local_media_profiles.router import router as local_media_profiles
    from backend.api.endpoints.stream_profiles.router import router as stream_profiles

    use_database(session.get_bind())
    app = FastAPI()
    for router in (download_profiles, stream_profiles, local_media_profiles):
        app.include_router(router)
    api_client = TestClient(app)
    response = api_client.get("/download-profiles/as-view", params={"status": ["enabled"], "limit": 5})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [], "limit": 5, "nextCursor": None, "previousCursor": None, "revision": None,
        "hasMore": False, "hasPrevious": False, "total": 0,
    }
    assert api_client.get("/stream-profiles/as-view", params={"streams_from": "source"}).status_code == 200
    assert api_client.get("/local-media-profiles/as-view", params={"used_for": ["movie", "video"]}).status_code == 200
    assert api_client.get("/local-media-profiles/as-view", params={"site": ["youtube"]}).status_code == 200
    assert api_client.get("/download-profiles/as-view", params={"status": "maybe"}).status_code == 422
    assert api_client.get("/download-profiles/as-view", params={"site": ["youtube"]}).status_code == 200
    assert api_client.get("/download-profiles/as-view/sites").json() == []
    assert api_client.get("/stream-profiles/as-view/sites").json() == []


def test_library_counts_say_which_tabs_the_library_has(session):
    from backend.api.endpoints.library.service import get_library_counts
    from backend.db.models import Movie
    from backend.types.media_types import MediaType

    session.add_all([_collection(index) for index in range(3)])
    session.add(Movie(
        source_key="dailywire", uuid="movie", type=MediaType.MOVIE.value, slug="movie", title="Movie",
        extended_title="Movie", author_name="Director", mature_rating="PG", description=None, duration=60,
    ))
    session.flush()

    counts = get_library_counts(session)

    assert (counts.collections, counts.movies, counts.videos) == (3, 1, 0)
