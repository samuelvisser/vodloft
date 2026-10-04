"""A populated pinned WireLoft database upgrades without losing its library."""
import importlib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker


def test_wireloft_upgrade_preserves_files_memberships_profiles_feeds_and_history(tmp_path, monkeypatch):
    from backend.db import core
    from backend.db.migrations import get_alembic_config, upgrade_database, get_head_revision
    from backend.db.models import Show, Season, Episode, SeriesDownloadProfile, PodcastDownloadProfile, RssStreamProfile
    from backend.db.models.local_media_profile import ShowLocalMediaProfile, DomainLocalMediaProfile
    from backend.db.models.media_item import Movie, MovieExtra, MovieExtraSource
    from backend.db.models.media_download import EpisodeMediaDownload, MediaDownloadHistory
    from backend.db.models.vodloft import (Artifact, ArtifactPlacement, CollectionEntry, CollectionDownloadProfile,
        CollectionStreamProfile, FeedSubscription, LegacyMediaLink, MediaDemand, MediaItem, MovieExtraParent, SourceReference)
    from config import get_settings
    db_path = tmp_path / 'upgrade.db'
    engine = create_engine(f'sqlite:///{db_path}', connect_args={'check_same_thread': False})
    event.listen(engine, 'connect', core._configure_sqlite_connection)
    sessions = sessionmaker(engine, autoflush=False)
    monkeypatch.setattr(core, '_engine', engine); monkeypatch.setattr(core, '_SessionLocal', sessions); monkeypatch.setattr(core, '_db_path', db_path)
    monkeypatch.setattr(get_settings().download_settings, 'download_root', tmp_path)
    command.upgrade(get_alembic_config(allow_version_storage_migration=True), 'a9d73b8e5f21')
    original = tmp_path / 'existing.mp3'; original.write_bytes(b'existing WireLoft audio bytes')
    with sessions() as session:
        profile = ShowLocalMediaProfile(name='Existing audio', slug='existing-audio', preferred_format='format_audio_only',
            output_template='/downloads/{{ show_title }}/{{ season_name }}/{{ episode_title }}.ext')
        show = Show(uuid='show', slug='show', title='Existing series', sharing_url='https://www.dailywire.com/show/show',
            membership_level='FREE', type='series', episode_identifier='seasonal', author_name='Host', author_slug='host')
        session.add_all([profile, show]); session.flush()
        first = Season(show_id=show.id, index=1, slug='season-1', name='Season 1')
        excluded = Season(show_id=show.id, index=2, slug='season-2', name='Season 2')
        session.add_all([first, excluded]); session.flush()
        episode = Episode(uuid='episode', show_id=show.id, season_id=first.id, index=1, episode_identifier='ep.S01E01',
            dw_episode_number='1', slug='episode', title='Existing episode', sharing_url='https://www.dailywire.com/episode/episode',
            publish_status='published', duration=180, published_date=datetime(2026, 9, 1, tzinfo=timezone.utc))
        other = Episode(uuid='other', show_id=show.id, season_id=excluded.id, index=2, episode_identifier='aux.1',
            slug='other', title='Extra', sharing_url='https://www.dailywire.com/episode/other', publish_status='published')
        session.add_all([episode, other]); session.flush()
        series = SeriesDownloadProfile(show_id=show.id, local_media_profile_id=profile.id, seasons=[first],
            include_upcoming_seasons=False, ep_id_type_list=['ep'], enable_profile=True)
        podcast = PodcastDownloadProfile(show_id=show.id, local_media_profile_id=profile.id,
            download_episode_count=4, download_days_in_past=30, delete_older_episodes=True, ep_id_type_list=['ep', 'aux'])
        stream = RssStreamProfile(show_id=show.id, token='kept-subscription-token', feed_url='old-value', max_items=3,
            overwrite_show_title='Custom podcast title', use_downloads=True, use_dw_stream=False,
            preferred_format='format_audio_only', prefer_exact_match=False, ep_id_type_list=['ep'],
            live_episode_handoff_ids=[episode.id])
        session.add_all([series, podcast, stream]); session.flush()
        download = EpisodeMediaDownload(media_item_id=episode.id, local_media_profile_id=profile.id,
            download_profile_id=series.id, file_path=str(original), artifact_status='available', downloaded_bytes=original.stat().st_size,
            artifact_stat_dev=str(original.stat().st_dev), artifact_stat_ino=str(original.stat().st_ino),
            artifact_size_bytes=original.stat().st_size, artifact_fingerprint=hashlib.sha256(original.read_bytes()).hexdigest(),
            format_downloaded='audio', downloaded_publish_status='published')
        session.add(download); session.flush()
        history = MediaDownloadHistory(media_download_id=download.id, action='available', event_metadata={'reason': 'existing'})
        session.add(history)
        movie = Movie(uuid='movie', slug='movie', title='Existing movie', sharing_url='https://www.dailywire.com/videos/movie')
        source = MovieExtraSource(slug='trailer', title='Trailer', sharing_url='https://www.dailywire.com/clips/trailer')
        session.add_all([movie, source]); session.flush()
        session.add(MovieExtra(uuid='trailer-placement', movie_id=movie.id, source_id=source.id, movie_extra_type='trailer'))
        session.commit()
        profile_id, show_id, episode_id = profile.id, show.id, episode.id
        series_id, stream_id, download_id = series.id, stream.id, download.id
    upgrade_database()
    with engine.connect() as connection:
        assert connection.execute(text('SELECT alembic_version_num FROM settings')).scalar_one() == get_head_revision()
        assert not connection.exec_driver_sql('PRAGMA foreign_key_check').all()
    context = SimpleNamespace(raise_if_cancelled=lambda: None, update_progress=lambda *args: None)
    legacy = importlib.import_module('backend.db.background_migrations.versions.8e5a2c9f41d0_vodloft_legacy_library')
    automation = importlib.import_module('backend.db.background_migrations.versions.a03f7e9bc261_vodloft_automation_conversion')
    policies = importlib.import_module('backend.db.background_migrations.versions.0b87c419ad62_vodloft_membership_policy_conversion')
    preparation = importlib.import_module('backend.db.background_migrations.versions.c64f8092de17_vodloft_feed_preparation_conversion')
    monkeypatch.setattr(automation.secret_store, 'save', lambda *args: 'fixture-secret')
    from dailywire_authorisation.storage import TokenStore
    monkeypatch.setattr(TokenStore, 'load', lambda *args: None)
    for _ in range(2):
        legacy._migrate(context); automation._convert(context); policies._convert(context); preparation._convert(context)
    with sessions() as session:
        migrated_profile = session.get(DomainLocalMediaProfile, profile_id)
        assert migrated_profile.enabled and not migrated_profile.impairment
        assert '{{ collection }}' in migrated_profile.output_template and '{{ group }}' in migrated_profile.output_template
        collection_id = session.scalar(select(LegacyMediaLink.item_id).where(LegacyMediaLink.legacy_type == 'show', LegacyMediaLink.legacy_id == show_id))
        item_id = session.scalar(select(LegacyMediaLink.item_id).where(LegacyMediaLink.legacy_type == 'episode', LegacyMediaLink.legacy_id == episode_id))
        assert len(session.scalars(select(CollectionEntry).where(CollectionEntry.collection_id == collection_id)).all()) == 2
        entry = session.scalar(select(CollectionEntry).where(CollectionEntry.item_id == item_id))
        assert entry.group == 'Season 1' and entry.role == 'episode'
        assert session.get(MediaItem, item_id).published_at.year == 2026
        policy = session.scalar(select(CollectionDownloadProfile).where(CollectionDownloadProfile.name == f'Imported download profile {series_id}'))
        assert policy.selected_groups == ['Season 1'] and policy.known_groups == ['Season 2', 'Season 1']
        assert not policy.include_future_groups and policy.member_roles == ['episode']
        assert len(session.scalars(select(CollectionDownloadProfile)).all()) == 2
        feed = session.scalar(select(CollectionStreamProfile).where(CollectionStreamProfile.name == f'Imported stream profile {stream_id}'))
        assert feed.max_items == 3 and feed.feed_title == 'Custom podcast title' and feed.member_roles == ['episode']
        assert feed.allow_other_renditions and feed.source_reference_id is not None
        from backend.db.models.vodloft import LiveAdmission
        admission = session.scalar(select(LiveAdmission))
        assert admission.item_id == item_id and admission.state == 'local'
        assert session.scalar(select(FeedSubscription)).token == 'kept-subscription-token'
        artifacts = session.scalars(select(Artifact)).all(); assert len(artifacts) == 1
        assert Path(artifacts[0].path).read_bytes() == original.read_bytes()
        assert session.scalar(select(ArtifactPlacement)).path == str(original)
        assert session.scalar(select(MediaDemand)).item_id == item_id
        assert len(session.scalars(select(MovieExtraParent)).all()) == 1
        assert session.scalar(select(MediaDownloadHistory)).media_download_id == download_id
        references = session.scalars(select(SourceReference)).all()
        assert len(references) == 5 and all(len(reference.upstream_id) == 36 for reference in references)
    assert original.read_bytes() == b'existing WireLoft audio bytes'
    engine.dispose()
