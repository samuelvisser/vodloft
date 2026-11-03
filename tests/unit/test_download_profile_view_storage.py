from __future__ import annotations

from datetime import datetime, timezone

from conftest import available_artifact
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_download_profile_view_reports_storage_of_its_own_downloads() -> None:
    import backend.db.models  # noqa: F401
    import task_manager.scheduler.db  # noqa: F401
    from backend.api.endpoints.download_profiles.as_view.service import (
        get_download_profile_view,
        get_download_profile_views_list,
    )
    from backend.db import Base
    from backend.db.models import (
        Collection, DownloadProfile, Episode, EpisodeMediaDownload, LocalMediaProfile, Season,
    )
    from backend.types.collection_types import CollectionType, EpisodeIdentifier
    from backend.types.download_profile_types import EpIdType, MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        collection = Collection(
            source_key="dailywire", uuid="collection-uuid", slug="show", title="Show", description=None,
            sharing_url="https://example.test/show", membership_level="FREE", type=CollectionType.PODCAST.value,
            episode_identifier=EpisodeIdentifier.NUMBERED.value, author_name="Host", author_slug="host",
        )
        audio = LocalMediaProfile(slug="audio", name="Audio", preferred_format="format_audio_only",
                                  output_template="/downloads/audio/{{ episode }}.ext")
        video = LocalMediaProfile(slug="video", name="Video", preferred_format="format_1080p",
                                  output_template="/downloads/video/{{ episode }}.ext")
        session.add_all([collection, audio, video])
        session.flush()

        def add_profile(local_media_profile):
            profile = DownloadProfile(
                collection_id=collection.id, local_media_profile_id=local_media_profile.id, enable_profile=True,
                ep_id_type_list=[EpIdType.EP.value], download_with_countdown=False, redownload_final=False,
                download_days_in_past=0, download_episode_count=0, delete_older_episodes=False,
            )
            session.add(profile)
            return profile

        audio_profile, video_profile = add_profile(audio), add_profile(video)
        season = Season(collection=collection, index=1, slug="season-1", name="Season 1")
        episodes = [
            Episode(
                source_key="dailywire", uuid=f"episode-{index}", type=MediaType.EPISODE.value, collection=collection,
                season=season, index=index, episode_identifier=f"ep{index}", slug=f"episode-{index}", title=f"Episode {index}",
                description="", duration=60, publish_status="published_final",
                sharing_url=f"https://example.test/show/{index}",
                published_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
            for index in (1, 2, 3)
        ]
        session.add_all(episodes)
        session.flush()

        def add_download(episode, local_media_profile, profile, **artifact):
            session.add(EpisodeMediaDownload(
                type=MediaType.EPISODE.value, media_item_id=episode.id,
                local_media_profile_id=local_media_profile.id,
                download_profile_id=profile.id if profile else None,
                file_path=f"/downloads/{local_media_profile.slug}/{episode.slug}.ext", **artifact,
            ))

        add_download(episodes[0], audio, audio_profile, **(available_artifact() | {"artifact_size_bytes": 1000}))
        add_download(episodes[1], audio, audio_profile, **(available_artifact() | {"artifact_size_bytes": 500}))
        # A download whose file is gone takes no space.
        add_download(episodes[2], audio, audio_profile, artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
                     artifact_size_bytes=4000)
        add_download(episodes[0], video, video_profile, **(available_artifact() | {"artifact_size_bytes": 7000}))
        session.commit()

        views = {view.id: view for view in get_download_profile_views_list(session)}

        assert views[audio_profile.id].storage_size_bytes == 1500
        assert views[video_profile.id].storage_size_bytes == 7000
        assert get_download_profile_view(session, audio_profile.id).storage_size_bytes == 1500
        assert views[audio_profile.id].model_dump(by_alias=True)["storageSizeBytes"] == 1500
    finally:
        session.close()
        engine.dispose()
