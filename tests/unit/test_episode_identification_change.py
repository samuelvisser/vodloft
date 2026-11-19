"""Changing how a collection numbers its episodes: the new identifiers, what the change would do, and the files."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from conftest import available_artifact, use_database
from profile_filters import line, with_filters
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

START = datetime(2026, 3, 1, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    use_database(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    s = Session(engine)
    yield s
    s.close()
    engine.dispose()


def _collection(s, *, source_key, identification, season_number=1):
    from backend.db.models import Collection, Season

    collection = Collection(
        source_key=source_key, uuid=f"{source_key}-show", slug="show", title="Show", description="",
        sharing_url="https://example.test/show", membership_level="FREE", type="series",
        episode_identifier=identification, author_name="Host", author_slug="host",
    )
    s.add(collection)
    s.flush()
    s.add(Season(collection=collection, index=1, slug="show-s1", name="One", season_number=season_number))
    s.flush()
    return collection


def _episode(s, collection, index, identifier, *, number=None, season=None, title=None):
    from backend.db.models import Episode

    episode = Episode(
        source_key=collection.source_key, uuid=f"ep-{index}", type="episode", collection=collection,
        season=season or collection.seasons[0], index=index, episode_identifier=identifier, slug=f"ep-{index}",
        title=title or f"Episode {index}", description="", duration=600.0, publish_status="published_final",
        sharing_url=f"https://example.test/{index}", published_date=START + timedelta(days=index),
        dw_episode_number=number,
    )
    s.add(episode)
    s.flush()
    return episode


def _date(index: int) -> str:
    from task_manager.tasks.helpers.general import datetime_to_string

    return f"ep.{datetime_to_string(START + timedelta(days=index))}"


def _identifiers(s, collection) -> dict[str, str]:
    from backend.db.models import Episode

    return {episode.slug: episode.episode_identifier for episode in s.query(Episode).filter_by(collection_id=collection.id)}


def _change(s, collection, identification):
    from backend.services.episode_identification import apply_identification, plan_identification
    from backend.types.collection_types import EpisodeIdentifier

    plan = plan_identification(s, collection, EpisodeIdentifier(identification))
    apply_identification(s, collection, plan)
    s.flush()
    return plan


def _daily_wire_show(s):
    """A Daily Wire show numbered by date: two episodes, an extra of the first, and a trailer."""
    collection = _collection(s, source_key="dailywire", identification="date_based", season_number=3)
    _episode(s, collection, 1, _date(1), number="100")
    _episode(s, collection, 2, _date(2), number="100.01")
    _episode(s, collection, 3, _date(3), number="101")
    _episode(s, collection, 4, "trailer.1", number=None, title="Official Trailer")
    return collection


def test_a_daily_wire_show_takes_the_numbers_the_daily_wire_gives_and_goes_back_to_dates(session):
    collection = _daily_wire_show(session)

    _change(session, collection, "numbered")
    assert collection.episode_identifier == "numbered"
    assert _identifiers(session, collection) == {
        "ep-1": "ep.100", "ep-2": "ep-extra.other.100.1", "ep-3": "ep.101", "ep-4": "trailer.1",
    }

    _change(session, collection, "seasonal")
    assert _identifiers(session, collection) == {
        "ep-1": "ep.S03E100", "ep-2": "ep-extra.other.S03E100.1", "ep-3": "ep.S03E101", "ep-4": "trailer.1",
    }

    # Back to dates gives every episode the identifier it had at first.
    _change(session, collection, "date_based")
    assert _identifiers(session, collection) == {
        "ep-1": _date(1), "ep-2": _date(2), "ep-3": _date(3), "ep-4": "trailer.1",
    }


def test_a_daily_wire_episode_without_a_number_is_auxiliary_when_numbered(session):
    collection = _collection(session, source_key="dailywire", identification="date_based")
    _episode(session, collection, 1, _date(1), number="7")
    _episode(session, collection, 2, _date(2), number=None)

    plan = _change(session, collection, "numbered")

    assert _identifiers(session, collection) == {"ep-1": "ep.7", "ep-2": "aux.1"}
    assert plan.counters["ep_id.latest_aux_num"] == 1
    assert collection.get_meta("ep_id.latest_aux_num") == "1"


def test_a_counted_collection_counts_its_videos_again_and_leaves_shorts_alone(session):
    from backend.db.models import Season

    collection = _collection(session, source_key="ytdlp", identification="date_based")
    first = collection.seasons[0]
    second = Season(collection=collection, index=2, slug="show-s2", name="Two", season_number=2)
    session.add(second)
    session.flush()
    _episode(session, collection, 1, _date(1), season=first)
    _episode(session, collection, 2, "short.1", season=first)
    _episode(session, collection, 3, _date(3), season=second)
    _episode(session, collection, 4, _date(4), season=first)

    _change(session, collection, "seasonal")
    assert _identifiers(session, collection) == {
        "ep-1": "ep.S01E01", "ep-2": "short.1", "ep-3": "ep.S02E01", "ep-4": "ep.S01E02",
    }

    _change(session, collection, "numbered")
    assert _identifiers(session, collection) == {"ep-1": "ep.1", "ep-2": "short.1", "ep-3": "ep.2", "ep-4": "ep.3"}

    _change(session, collection, "date_based")
    assert _identifiers(session, collection) == {
        "ep-1": _date(1), "ep-2": "short.1", "ep-3": _date(3), "ep-4": _date(4),
    }


def test_a_season_without_a_number_refuses_seasonal_numbering(session):
    from backend.services.episode_identification import plan_identification
    from backend.services.errors import ServiceError
    from backend.types.collection_types import EpisodeIdentifier

    collection = _collection(session, source_key="dailywire", identification="date_based", season_number=0)
    _episode(session, collection, 1, _date(1), number="100")

    with pytest.raises(ServiceError) as refused:
        plan_identification(session, collection, EpisodeIdentifier.SEASONAL)
    assert refused.value.field == "episodeIdentifier"


def _profile(s, collection, *filters, template="/downloads/{{ collection }}/{{ episode_label }}.ext"):
    from backend.db.models import LocalMediaProfile
    from backend.db.models.download_profile import DownloadProfile

    local = LocalMediaProfile(slug="local", name="Plex", preferred_format="format_1080p", output_template=template)
    s.add(local)
    s.flush()
    profile = DownloadProfile(
        collection=collection, local_media_profile=local, enable_profile=True,
        download_with_countdown=False, redownload_final=False, delete_older_episodes=False,
    )
    s.add(profile)
    with_filters(profile, *filters)
    s.flush()
    return profile


def _download(s, profile, episode, **values):
    from backend.db.models.media_download import EpisodeMediaDownload

    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=profile.local_media_profile_id,
        download_profile_id=profile.id, **{"file_path": f"/tmp/show-{episode.id}.mkv", **available_artifact(), **values},
    )
    s.add(download)
    s.flush()
    return download


def test_the_preview_counts_files_to_rename_and_downloads_the_filters_would_leave_out(session):
    from backend.db.models import Episode
    from backend.services.episode_identification import preview_identification
    from backend.types.collection_types import EpisodeIdentifier

    collection = _daily_wire_show(session)
    # Under dates the Daily Wire extra is an episode; numbered, it is an extra this profile leaves out.
    profile = _profile(session, collection, line("only", "types", episode_types=["ep"]))
    for episode in session.query(Episode).filter(Episode.slug.in_(["ep-1", "ep-2"])):
        _download(session, profile, episode)
    session.commit()

    preview = preview_identification(session, collection, EpisodeIdentifier.NUMBERED)

    assert preview.episodes == 4
    assert preview.episodes_renumbered == 3
    assert len(preview.changes) == 3
    assert [(example.before, example.after) for example in preview.changes][0] == (
        (START + timedelta(days=3)).strftime("%Y-%m-%d %H:%M"), "101",
    )
    assert [(item.name, item.files_renamed) for item in preview.profiles] == [("Plex", 2)]
    assert [(item.name, item.removed, item.no_longer_wanted) for item in preview.download_profiles] == [("Plex", 0, 1)]
    assert preview.busy is None
    # Nothing changed: the preview only tried the new numbers.
    assert collection.episode_identifier == "date_based"
    assert _identifiers(session, collection)["ep-2"] == _date(2)
    assert not session.dirty


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg")
def test_rewriting_metadata_retags_the_file_without_downloading_and_clears_numbers_that_no_longer_apply(
        session, tmp_path,
):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.services.metadata_rewrite import (
        plan_metadata_rewrites, record_metadata_rewrite, rewrite_metadata,
    )

    media = tmp_path / "episode.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
         "-c:v", "mpeg4", "-metadata", "title=Old title", "-metadata", "season_number=3",
         "-metadata", "episode_id=100", "-movflags", "+use_metadata_tags", str(media)],
        check=True,
    )
    collection = _collection(session, source_key="dailywire", identification="date_based", season_number=3)
    episode = _episode(session, collection, 1, _date(1), number="100", title="New title")
    profile = _profile(session, collection)
    profile.local_media_profile.metadata_mode = "embed_and_nfo"
    download = _download(session, profile, episode, file_path=str(media), **available_artifact(media))
    session.commit()

    rewrites, untaggable = plan_metadata_rewrites(
        session, collection_id=collection.id, local_media_profile_id=profile.local_media_profile_id,
    )
    assert untaggable == 0 and len(rewrites) == 1
    rewrite_metadata(rewrites[0])
    record_metadata_rewrite(rewrites[0])

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(media)],
        check=True, capture_output=True, text=True,
    )
    tags = {key.lower(): value for key, value in json.loads(probe.stdout)["format"]["tags"].items()}
    assert tags["title"] == "New title"
    # Numbered by date, the episode has no season or episode number any more.
    assert "season_number" not in tags and "episode_id" not in tags
    nfo = media.with_suffix(".nfo")
    assert "New title" in nfo.read_text()

    session.expire_all()
    stored = session.get(EpisodeMediaDownload, download.id)
    assert stored.artifact_size_bytes == media.stat().st_size
    assert stored.nfo_path == str(nfo)


def test_asking_the_api_for_another_identification_starts_an_operation(session):
    import task_manager.scheduler.db  # noqa: F401
    from backend.api.endpoints.collections.service import change_collection_identification
    from backend.api.models.collection import CollectionIdentificationChangeAPIRequest
    from backend.db import Base
    from task_manager.scheduler.db import TaskDefinition, TaskOperation

    Base.metadata.create_all(session.get_bind())
    session.add(TaskDefinition(
        key="change_collection_identification", title="Change", description="", allowed_resource_types=[],
    ))
    _daily_wire_show(session)
    session.commit()

    # The request model keeps the identification as the plain string the form sent.
    body = CollectionIdentificationChangeAPIRequest.model_validate({"episodeIdentifier": "numbered"})
    accepted = change_collection_identification(session, "show", body)

    operation = session.get(TaskOperation, accepted.operation_id)
    assert operation.kind == "collection.change_identification"
    assert operation.context["episode_identifier"] == "numbered"
