from __future__ import annotations

from conftest import available_artifact
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.security.access import Access
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class _FakeURL:
    def __init__(self, value: str):
        self._value = value

    def __str__(self) -> str:
        return self._value


class _FakeRequest:
    def __init__(self, base_url: str = "https://vodloft.test/", method: str = "GET"):
        self.base_url = _FakeURL(base_url)
        self.method = method


@pytest.fixture
def db_session():
    import backend.db.models  # noqa: F401
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    session = Session(engine)
    Base.metadata.create_all(engine)
    yield session
    session.close()
    engine.dispose()


def _make_collection(
    session: Session,
    *,
    slug: str = "collection",
    episode_identifier: str | None = None,
    collection_type: str | None = None,
):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title="Test Show",
        description="Description",
        sharing_url=f"https://www.dailywire.com/{slug}",
        membership_level="FREE",
        type=collection_type or CollectionType.PODCAST.value,
        episode_identifier=(
            episode_identifier or EpisodeIdentifier.NUMBERED.value
        ),
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


def _make_season(
    session: Session,
    collection,
    *,
    index: int = 1,
    season_number: int = 1,
    name: str = "Season 1",
):
    from backend.db.models import Season

    season = Season(
        collection=collection,
        index=index,
        slug=f"season-{index}",
        name=name,
        season_number=season_number,
    )
    session.add(season)
    session.flush()
    return season


def _make_episode(
    session: Session,
    collection,
    season,
    *,
    index: int,
    status: str = "published_final",
    when: datetime | None = None,
    episode_identifier: str | None = None,
    dw_episode_number: str | None = None,
):
    from backend.db.models import Episode

    when = when or datetime.now(timezone.utc)
    episode = Episode(
        source_key="dailywire",
        uuid=f"episode-{index}-uuid",
        type="episode",
        collection=collection,
        season=season,
        index=index,
        episode_identifier=episode_identifier or f"ep.{index}",
        dw_episode_number=dw_episode_number,
        slug=f"episode-{index}",
        title=f"Episode {index}",
        description="Description",
        duration=1800.0,
        publish_status=status,
        sharing_url=f"https://www.dailywire.com/episode-{index}",
        published_date=when if status != "live" else None,
        went_live_date=when if status == "live" else None,
    )
    session.add(episode)
    session.flush()
    return episode


def _make_local_media_profile(
    session: Session,
    *,
    slug: str,
    preferred_format: str,
):
    from backend.db.models import LocalMediaProfile

    profile = LocalMediaProfile(
        slug=slug,
        name=slug,
        output_template=f"/downloads/{slug}/{{{{ episode_title }}}}.ext",
        preferred_format=preferred_format,
    )
    session.add(profile)
    session.flush()
    return profile


def _make_available_download(
    session: Session,
    episode,
    profile,
    path: Path,
):
    from backend.db.models import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media-data")
    download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episode.id,
        local_media_profile_id=profile.id,
        file_path=str(path),
        **available_artifact(),
        downloaded_bytes=path.stat().st_size,
        downloaded_at=datetime.now(timezone.utc),
        downloaded_publish_status=episode.publish_status,
    )
    session.add(download)
    session.flush()
    return download


def _make_rss_profile(
    session: Session,
    collection,
    *,
    mode: str = "audio_hls",
    preferred_format: str = "format_1080p",
    use_downloads: bool = True,
    use_source_stream: bool = False,
    max_items: int = 0,
):
    from backend.db.models import RssStreamProfile

    profile = RssStreamProfile(
        collection=collection,
        enable_profile=True,
        token="token",
        use_downloads=use_downloads,
        use_source_stream=use_source_stream,
        preferred_format=preferred_format,
        prefer_exact_match=False,
        ep_id_type_list=["ep"],
        feed_url="https://vodloft.test/feeds/rss/token/collection.xml",
        video_output_mode=mode,
        stream_live_episodes=False,
        live_episode_handoff_ids=[],
        max_items=max_items,
    )
    session.add(profile)
    session.flush()
    return profile


def test_download_only_feed_excludes_episodes_without_relevant_local_media(
        db_session,
        tmp_path,
):
    from backend.api.endpoints.feeds.service import get_feed_items

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    newest = _make_episode(db_session, collection, season, index=2)
    older = _make_episode(
        db_session,
        collection,
        season,
        index=1,
        when=datetime.now(timezone.utc) - timedelta(days=1),
    )
    video = _make_local_media_profile(
        db_session,
        slug="video",
        preferred_format="format_1080p",
    )
    local = _make_available_download(
        db_session,
        newest,
        video,
        tmp_path / "newest.mp4",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=True,
        use_source_stream=False,
    )

    items = get_feed_items(db_session, profile)

    assert items == [(newest, local)]
    assert older not in [episode for episode, _ in items]


def test_dailywire_enabled_feed_keeps_undownloaded_episode_with_stable_url(
        db_session,
):
    from backend.api.endpoints.feeds.service import get_feed_items, render_rss_feed

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="audio_hls",
        use_downloads=True,
        use_source_stream=True,
    )

    assert get_feed_items(db_session, profile) == [(episode, None)]

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()
    assert (
        "https://vodloft.test/feeds/rss/token/episodes/episode-1/audio.m4a"
        in xml
    )
    assert (
        "https://vodloft.test/feeds/rss/token/episodes/episode-1/video.m3u8"
        in xml
    )
    # Only VODLoft's own media URLs, never one of The Daily Wire's.
    assert "media.dailywire" not in xml.lower() and "dailywire.com/episode-1" not in xml.lower()


@pytest.mark.parametrize(
    ("mode", "local_kind", "stable_suffixes"),
    [
        ("audio_hls", "hls", ("audio.m4a", "video.m3u8")),
        ("audio_mp4", "mp4", ("audio.m4a", "video.mp4")),
        ("mp4", "mp4", ("video.mp4",)),
        ("mp4_hls", "hls", ("video.mp4", "video.m3u8")),
    ],
)
def test_rss_media_urls_do_not_change_when_download_appears(
        db_session,
        tmp_path,
        mode,
        local_kind,
        stable_suffixes,
):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from downloader.storage.identity import inspect_artifact
    from downloader import hls_asset_marker, hls_asset_root

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        mode=mode,
        use_downloads=True,
        use_source_stream=True,
    )

    before = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    if local_kind == "hls":
        local_profile = _make_local_media_profile(
            db_session,
            slug=f"{mode}-hls",
            preferred_format="format_hls",
        )
        master = tmp_path / f"{mode}.m3u8"
        master.write_text(
            "#EXTM3U\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=854x480\n"
            "hls/480p/playlist.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2,RESOLUTION=1280x720\n"
            "hls/720p/playlist.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=3,RESOLUTION=1920x1080\n"
            "hls/1080p/playlist.m3u8\n"
        )
        assets = hls_asset_root(master)
        assets.mkdir()
        hls_asset_marker(master).write_text("owned")
        for height in (480, 720, 1080):
            directory = assets / f"{height}p"
            directory.mkdir()
            (directory / "media.ts").write_bytes(b"segment")
            (directory / "playlist.m3u8").write_text(
                "#EXTM3U\n"
                "#EXT-X-VERSION:4\n"
                "#EXTINF:6.0,\n"
                "#EXT-X-BYTERANGE:7@0\n"
                "media.ts\n"
                "#EXT-X-ENDLIST\n"
            )
        download = _make_available_download(
            db_session,
            episode,
            local_profile,
            master,
        )
        identity = inspect_artifact(master)
        download.artifact_stat_dev = identity.stat_dev
        download.artifact_stat_ino = identity.stat_ino
        download.artifact_size_bytes = identity.size_bytes
        download.artifact_fingerprint = identity.fingerprint
        download.downloaded_bytes = identity.size_bytes
        db_session.flush()
    else:
        local_profile = _make_local_media_profile(
            db_session,
            slug=f"{mode}-video",
            preferred_format="format_1080p",
        )
        _make_available_download(
            db_session,
            episode,
            local_profile,
            tmp_path / f"{mode}.mp4",
        )

    after = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    base = "https://vodloft.test/feeds/rss/token/episodes/episode-1/"
    for suffix in stable_suffixes:
        stable_url = f"{base}{suffix}"
        assert stable_url in before
        assert stable_url in after

    guid = f"<guid isPermaLink=\"false\">{episode.uuid}</guid>"
    assert guid in before
    assert guid in after


def test_max_items_keeps_newest_feed_entries(db_session):
    from backend.api.endpoints.feeds.service import get_feed_items

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    now = datetime.now(timezone.utc)
    newest = _make_episode(db_session, collection, season, index=3, when=now)
    second = _make_episode(
        db_session,
        collection,
        season,
        index=2,
        when=now - timedelta(hours=1),
    )
    _make_episode(
        db_session,
        collection,
        season,
        index=1,
        when=now - timedelta(hours=2),
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
        max_items=2,
    )

    assert [episode for episode, _ in get_feed_items(db_session, profile)] == [
        newest,
        second,
    ]


def test_seasonal_feed_emits_apple_and_podcasting20_numbering(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.types.collection_types import EpisodeIdentifier

    collection = _make_collection(
        db_session,
        episode_identifier=EpisodeIdentifier.SEASONAL.value,
    )
    season = _make_season(
        db_session,
        collection,
        index=4,
        season_number=2,
        name="Second Season",
    )
    _make_episode(
        db_session,
        collection,
        season,
        index=7,
        episode_identifier="ep.S02E07",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>episodic</itunes:type>" in xml
    assert "<itunes:season>2</itunes:season>" in xml
    assert "<itunes:episode>7</itunes:episode>" in xml
    assert "<itunes:episodeType>full</itunes:episodeType>" in xml
    assert '<podcast:season name="Second Season">2</podcast:season>' in xml
    assert "<podcast:episode>7</podcast:episode>" in xml


def test_series_feed_is_serial_even_with_seasonal_identifiers(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = _make_collection(
        db_session,
        episode_identifier=EpisodeIdentifier.SEASONAL.value,
        collection_type=CollectionType.SERIES.value,
    )
    season = _make_season(
        db_session,
        collection,
        season_number=1,
        name="Season 1",
    )
    _make_episode(
        db_session,
        collection,
        season,
        index=1,
        episode_identifier="ep.S01E01",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>serial</itunes:type>" in xml
    assert "<itunes:season>1</itunes:season>" in xml
    assert "<itunes:episode>1</itunes:episode>" in xml
    assert '<podcast:season name="Season 1">1</podcast:season>' in xml
    assert "<podcast:episode>1</podcast:episode>" in xml


def test_seasonal_attached_extra_keeps_parent_episode_number(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.types.collection_types import EpisodeIdentifier

    collection = _make_collection(
        db_session,
        episode_identifier=EpisodeIdentifier.SEASONAL.value,
    )
    season = _make_season(
        db_session,
        collection,
        season_number=3,
        name="Season 3",
    )
    _make_episode(
        db_session,
        collection,
        season,
        index=1,
        episode_identifier="ep-extra.other.S03E12.1",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )
    profile.ep_id_type_list = ["ep-extra"]

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:season>3</itunes:season>" in xml
    assert "<itunes:episode>12</itunes:episode>" in xml
    assert "<itunes:episodeType>bonus</itunes:episodeType>" in xml
    assert '<podcast:season name="Season 3">3</podcast:season>' in xml
    assert "<podcast:episode>12.1</podcast:episode>" in xml


def test_numbered_episodic_feed_emits_episode_metadata(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(
        db_session,
        collection,
        season,
        index=27,
        episode_identifier="ep.27",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>episodic</itunes:type>" in xml
    assert "<itunes:episode>27</itunes:episode>" in xml
    assert "<itunes:episodeType>full</itunes:episodeType>" in xml
    assert "<podcast:episode>27</podcast:episode>" in xml
    assert "<itunes:season>" not in xml
    assert "<podcast:season" not in xml


def test_numbered_episodic_bonus_uses_parent_episode_number(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(
        db_session,
        collection,
        season,
        index=1,
        episode_identifier="ep-extra.other.27.2",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )
    profile.ep_id_type_list = ["ep-extra"]

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>episodic</itunes:type>" in xml
    assert "<itunes:episode>27</itunes:episode>" in xml
    assert "<itunes:episodeType>bonus</itunes:episodeType>" in xml
    assert "<podcast:episode>27.2</podcast:episode>" in xml


def test_date_based_podcast_omits_episode_numbers(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.types.collection_types import EpisodeIdentifier

    collection = _make_collection(
        db_session,
        episode_identifier=EpisodeIdentifier.DATE_BASED.value,
    )
    season = _make_season(db_session, collection)
    _make_episode(
        db_session,
        collection,
        season,
        index=91,
        episode_identifier="ep.2026-09-26T09:00:00.000000",
        dw_episode_number="2497.10",
    )
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>episodic</itunes:type>" in xml
    assert "<itunes:episodeType>full</itunes:episodeType>" in xml
    assert "<itunes:episode>" not in xml
    assert "<podcast:episode>" not in xml
    assert "<itunes:season>" not in xml
    assert "<podcast:season" not in xml


def test_get_source_stream_url_selects_requested_media(
        db_session,
        monkeypatch,
):
    import backend.api.endpoints.feeds.service as service

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        use_downloads=False,
        use_source_stream=True,
    )

    from sources import EpisodeMedia, get_source

    source = get_source(episode.source_key)

    def episode_media(*, slug, members_only, interactive=False):
        assert slug == episode.slug
        assert members_only is False
        assert interactive is True
        return EpisodeMedia(
            audio_url="https://media.example/audio.m4a",
            video_url="https://media.example/video.m3u8",
        )

    monkeypatch.setattr(source, "episode_media", episode_media)

    assert service.get_source_stream_url(
        profile,
        episode,
        media_kind="audio",
    ) == "https://media.example/audio.m4a"
    assert service.get_source_stream_url(
        profile,
        episode,
        media_kind="video",
    ) == "https://media.example/video.m3u8"


def test_create_stream_profile_generates_plain_stable_feed_url(db_session):
    from backend.api.endpoints.rss_stream_profiles.service import (
        create_stream_profile_rss,
    )
    from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate

    collection = _make_collection(db_session)
    body = RssStreamProfileAPICreate(
        collection_id=collection.id,
        title=collection.title,
        enable_profile=True,
        use_downloads=True,
        use_source_stream=True,
        preferred_format="format_1080p",
        prefer_exact_match=False,
        video_output_mode="audio_hls",
    )

    created = create_stream_profile_rss(db_session, _FakeRequest(), body, Access.full())

    from backend.db.models import RssStreamProfile

    stored = db_session.get(RssStreamProfile, created.id)
    assert stored is not None
    assert stored.overwrite_collection_title is None
    assert created.effective_title == collection.title
    assert created.feed_url.startswith("https://vodloft.test/feeds/rss/")
    assert created.feed_url.endswith("/collection.xml")
    assert "dwVideoMethod" not in created.feed_url
    assert "?" not in created.feed_url


def test_regenerating_a_feed_url_puts_it_on_vodlofts_address(db_session):
    from backend.api.endpoints.rss_stream_profiles.service import regenerate_stream_profile_rss_token

    collection = _make_collection(db_session)
    profile = _make_rss_profile(db_session, collection)
    profile.feed_url = "http://wireloft.test/feeds/rss/token/collection.xml"  # As imported from WireLoft.

    regenerated = regenerate_stream_profile_rss_token(
        db_session, Access.full(), _FakeRequest("https://vodloft.test/"), profile.id,
    )

    assert profile.token != "token"
    assert regenerated.feed_url == f"https://vodloft.test/feeds/rss/{profile.token}/{collection.slug}.xml"


def test_stream_profile_custom_title_is_persisted_used_and_can_be_cleared(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.api.endpoints.rss_stream_profiles.service import (
        create_stream_profile_rss,
        update_stream_profile_rss,
    )
    from backend.api.models.rss_stream_profile import (
        RssStreamProfileAPICreate,
        RssStreamProfileAPIUpdate,
    )
    from backend.db.models import RssStreamProfile

    collection = _make_collection(db_session)
    custom_title = "My Custom Podcast"
    created = create_stream_profile_rss(
        db_session,
        _FakeRequest(),
        RssStreamProfileAPICreate(
            collection_id=collection.id,
            title=custom_title,
            enable_profile=True,
            use_downloads=True,
            use_source_stream=True,
            preferred_format="format_1080p",
            prefer_exact_match=False,
            video_output_mode="audio_hls",
        ),
        Access.full(),
    )

    stored = db_session.get(RssStreamProfile, created.id)
    assert stored is not None
    assert stored.overwrite_collection_title == custom_title
    assert created.effective_title == custom_title
    assert f"<title>{custom_title}</title>" in render_rss_feed(
        db_session,
        _FakeRequest(),
        stored,
    ).decode()

    updated = update_stream_profile_rss(
        db_session,
        Access.full(),
        created.id,
        RssStreamProfileAPIUpdate(
            title=collection.title,
            enable_profile=True,
            use_downloads=True,
            use_source_stream=True,
            preferred_format="format_1080p",
            prefer_exact_match=False,
            video_output_mode="audio_hls",
            feed_url=created.feed_url,
        ),
    )

    assert stored.overwrite_collection_title is None
    assert updated.effective_title == collection.title


def test_api_defaults_to_audio_hls_with_live_streaming_off():
    from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate

    profile = RssStreamProfileAPICreate(
        collection_id=1,
        title="Test Show",
        enable_profile=True,
        use_downloads=True,
        use_source_stream=True,
        preferred_format="format_1080p",
        prefer_exact_match=False,
    )

    assert profile.video_output_mode.value == "audio_hls"
    assert profile.stream_live_episodes is False



def test_stream_profile_rejects_local_hls_as_preferred_format():
    from pydantic import ValidationError

    from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate

    with pytest.raises(ValidationError, match="Local Media Profile download format"):
        RssStreamProfileAPICreate(
            collection_id=1,
            title="Test Show",
            enable_profile=True,
            use_downloads=True,
            use_source_stream=True,
            preferred_format="format_hls",
            prefer_exact_match=False,
        )


def test_live_streaming_requires_hls_video_output_mode():
    from pydantic import ValidationError

    from backend.api.models.rss_stream_profile import RssStreamProfileAPICreate

    with pytest.raises(ValidationError, match="requires an HLS"):
        RssStreamProfileAPICreate(
            collection_id=1,
            title="Test Show",
            enable_profile=True,
            use_downloads=True,
            use_source_stream=True,
            preferred_format="format_1080p",
            prefer_exact_match=False,
            video_output_mode="audio_mp4",
            stream_live_episodes=True,
        )



def _make_hls_bundle(path: Path) -> None:
    from downloader import hls_asset_marker, hls_asset_root

    path.write_text(
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=854x480\n"
        "hls/480p/playlist.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2,RESOLUTION=1280x720\n"
        "hls/720p/playlist.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=3,RESOLUTION=1920x1080\n"
        "hls/1080p/playlist.m3u8\n"
    )
    assets = hls_asset_root(path)
    assets.mkdir()
    hls_asset_marker(path).write_text("owned")
    for height in (480, 720, 1080):
        directory = assets / f"{height}p"
        directory.mkdir()
        (directory / "media.ts").write_bytes(b"segment")
        (directory / "playlist.m3u8").write_text(
            "#EXTM3U\n"
            "#EXT-X-VERSION:4\n"
            "#EXTINF:6.0,\n"
            "#EXT-X-BYTERANGE:7@0\n"
            "media.ts\n"
            "#EXT-X-ENDLIST\n"
        )


def test_download_only_audio_hls_requires_both_advertised_local_sources(
        db_session,
        tmp_path,
):
    from backend.api.endpoints.feeds.service import get_feed_items

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="audio_hls",
        use_downloads=True,
        use_source_stream=False,
    )

    hls_profile = _make_local_media_profile(
        db_session,
        slug="hls",
        preferred_format="format_hls",
    )
    hls_path = tmp_path / "episode.m3u8"
    hls_download = _make_available_download(
        db_session,
        episode,
        hls_profile,
        hls_path,
    )
    _make_hls_bundle(hls_path)
    hls_download.downloaded_bytes = sum(
        item.stat().st_size
        for item in hls_path.with_name(hls_path.name + ".assets").rglob("*")
        if item.is_file()
    )
    db_session.flush()

    assert get_feed_items(db_session, profile) == []

    audio_profile = _make_local_media_profile(
        db_session,
        slug="audio",
        preferred_format="format_audio_only",
    )
    audio_download = _make_available_download(
        db_session,
        episode,
        audio_profile,
        tmp_path / "episode.m4a",
    )

    assert get_feed_items(db_session, profile) == [(episode, audio_download)]


def test_download_only_mp4_hls_requires_both_advertised_video_sources(
        db_session,
        tmp_path,
):
    from backend.api.endpoints.feeds.service import get_feed_items

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4_hls",
        use_downloads=True,
        use_source_stream=False,
    )

    video_profile = _make_local_media_profile(
        db_session,
        slug="video",
        preferred_format="format_1080p",
    )
    mp4_download = _make_available_download(
        db_session,
        episode,
        video_profile,
        tmp_path / "episode.mp4",
    )

    assert get_feed_items(db_session, profile) == []

    hls_profile = _make_local_media_profile(
        db_session,
        slug="hls",
        preferred_format="format_hls",
    )
    hls_path = tmp_path / "episode.m3u8"
    _make_available_download(
        db_session,
        episode,
        hls_profile,
        hls_path,
    )
    _make_hls_bundle(hls_path)

    assert get_feed_items(db_session, profile) == [(episode, mp4_download)]


def test_a_downloaded_audio_enclosure_gives_the_file_size(db_session, tmp_path):
    from backend.api.endpoints.feeds.service import render_rss_feed

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1)
    audio = _make_local_media_profile(db_session, slug="audio", preferred_format="format_audio_only")
    download = _make_available_download(db_session, episode, audio, tmp_path / "episode.m4a")
    download.artifact_size_bytes = 10
    episode.duration = 3600.0
    db_session.flush()
    profile = _make_rss_profile(db_session, collection, mode="audio_mp4", preferred_format="format_audio_only")

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    # The file's own ten bytes, not the 57,600,000 that an hour streamed at 128 kbit/s would get.
    assert 'length="10"' in xml


def test_feed_type_follows_the_collection_episode_order(db_session):
    from backend.api.endpoints.feeds.service import render_rss_feed
    from backend.types.collection_types import EpisodeOrder

    collection = _make_collection(db_session)
    assert collection.episode_order == EpisodeOrder.NEWEST_FIRST.value
    collection.episode_order = EpisodeOrder.OLDEST_FIRST.value
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1)
    profile = _make_rss_profile(
        db_session,
        collection,
        mode="mp4",
        use_downloads=False,
        use_source_stream=True,
    )

    xml = render_rss_feed(db_session, _FakeRequest(), profile).decode()

    assert "<itunes:type>serial</itunes:type>" in xml
