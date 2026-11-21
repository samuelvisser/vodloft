"""A Collection whose own yt-dlp options have --allow-unplayable-formats lets yt-dlp try its media protected by DRM."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import use_database
from profile_filters import line


@pytest.fixture
def session():
    from backend.db.core import Base
    import backend.api.endpoints.videos.router  # noqa: F401  (loads every model first)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _collection(session, options="--allow-unplayable-formats", source_key="ytdlp"):
    from backend.db.models import Collection, Episode, Season

    collection = Collection(
        uuid="u", slug="PL1", source_key=source_key, title="A playlist", sharing_url="https://site.example/PL1",
        membership_level="FREE", type="podcast", episode_identifier="numbered", author_name="A", author_slug="a",
        ytdlp_options=options,
    )
    session.add(collection)
    season = Season(collection=collection, index=1, slug="s1", name="One")
    session.add(season)
    for index, (slug, drm) in enumerate((("open", False), ("locked", True)), start=1):
        session.add(Episode(
            source_key=source_key, uuid=f"ep-{slug}", type="episode", sharing_url=f"https://site.example/{slug}",
            collection=collection, season=season, slug=slug, title=f"Episode {slug}", index=index, episode_identifier=f"ep.{index}",
            publish_status="published_final", drm_protected=drm,
            published_date=datetime(2026, 3, index, tzinfo=timezone.utc),
        ))
    session.flush()
    return collection


@pytest.mark.parametrize(("text", "allowed"), [
    ("", False),
    ("--allow-unplayable-formats", True),
    ("--retries 3 --allow-unplayable-formats", True),
    ("--allow-unplayable", True),
    ("# --allow-unplayable-formats", False),
    ("--allow-unplayable-formats\n--no-allow-unplayable-formats", False),
    # Options that can not be used are never handed to yt-dlp.
    ("--allow-unplayable-formats -o x", False),
])
def test_options_that_allow_unplayable_formats(text, allowed):
    from sources.ytdlp_options import allows_unplayable_formats

    assert allows_unplayable_formats(text) is allowed


def test_the_option_is_left_out_for_other_media():
    from sources.ytdlp_options import without_unplayable_formats

    arguments = ("--retries", "3", "--allow-unplay", "--referer", "-x", "--no-allow-unplayable-formats", "-N", "4")
    assert without_unplayable_formats(arguments) == ("--retries", "3", "--referer", "-x", "-N", "4")


def test_unplayable_formats_download_one_file_and_process_nothing():
    from downloader import DownloadError
    from downloader.plan import YtdlpChapters, YtdlpSponsorBlock
    from downloader.ytdlp import resolve_ytdlp_source

    source = resolve_ytdlp_source(
        "https://site.example/v", command=("yt-dlp",), preferred_format="format_1080p", audio_only=False,
        custom_options=("--allow-unplayable-formats",), unplayable=True,
        sponsorblock=YtdlpSponsorBlock(cut=("sponsor",)), chapters=YtdlpChapters(keep=True, cut=("Intro",)),
    )
    command = source.ytdlp_command
    assert command[:2] == ("yt-dlp", "--allow-unplayable-formats")
    assert command[command.index("-f") + 1] == "b[ext=mp4]"
    assert command[command.index("-S") + 1].startswith("res:1080,")
    for processing in ("--merge-output-format", "--remux-video", "-x", "--sponsorblock-remove", "--remove-chapters"):
        assert processing not in command
    assert (source.extension, source.ytdlp_unplayable, source.ytdlp_sponsorblock.enabled) == ("mp4", True, False)

    audio = resolve_ytdlp_source(
        "https://site.example/v", command=("yt-dlp",), preferred_format="format_1080p", audio_only=True, unplayable=True,
    )
    assert audio.extension == "m4a" and "-x" not in audio.ytdlp_command

    with pytest.raises(DownloadError):
        resolve_ytdlp_source("https://site.example/v", command=("yt-dlp",), preferred_format="format_hls",
                             audio_only=False, unplayable=True)
    with pytest.raises(DownloadError):
        resolve_ytdlp_source("https://site.example/v", command=("yt-dlp",), preferred_format="format_1080p",
                             audio_only=False, unplayable=True, section=(0.0, 10.0))


def test_profiles_download_protected_episodes_and_can_filter_them(session):
    from backend.services.episode_filters import EpisodeSelection, evaluate

    collection = _collection(session)

    def wanted(*filters):
        selection = EpisodeSelection(collection=collection, download_with_countdown=False, filters=filters)
        return sorted(episode.slug for episode in evaluate(session, selection).wanted)

    assert wanted() == ["locked", "open"]
    assert wanted(line("only", "unplayable")) == ["locked"]
    assert wanted(line("skip", "unplayable")) == ["open"]

    collection.ytdlp_options = ""
    assert wanted() == ["open"]


def test_only_a_source_with_ytdlp_options_tries_unplayable_formats(session):
    from backend.services.unplayable_formats import blocked_by_drm, collection_allows_unplayable_formats

    collection = _collection(session, source_key="npo")
    locked = next(episode for episode in collection.episodes if episode.drm_protected)
    assert not collection_allows_unplayable_formats(collection)
    assert blocked_by_drm(locked)

    collection.source_key = "ytdlp"
    assert collection_allows_unplayable_formats(collection)
    assert not blocked_by_drm(locked)


def _download(session, collection, slug):
    from backend.db.models import CollectionLocalMediaProfile
    from backend.db.models.media_download import EpisodeMediaDownload

    episode = next(episode for episode in collection.episodes if episode.slug == slug)
    local = CollectionLocalMediaProfile(slug="collections", name="Collections", preferred_format="format_1080p",
                                        output_template="/downloads/{{ collection_title }}/{{ episode_title }}.ext")
    session.add(local)
    session.flush()
    download = EpisodeMediaDownload(
        type="episode", media_item_id=episode.id, local_media_profile_id=local.id, artifact_status="absent", file_path="x",
    )
    session.add(download)
    session.flush()
    return download


def test_a_refused_unplayable_download_fails_without_retry(session):
    from task_manager.tasks.download_adapter import _stop_unplayable_retry

    collection = _collection(session)
    download = _download(session, collection, "locked")
    assert _stop_unplayable_retry(session, download.id) is True
    assert download.automatic_retry_suppressed is True
    # Its download stays offered.
    assert download.media.drm_protected is True


def test_media_found_protected_while_downloading_is_tried_again_with_unplayable_formats(session):
    from task_manager.tasks.download_adapter import _TRY_UNPLAYABLE, _mark_drm_protected, _stop_unplayable_retry

    collection = _collection(session)
    download = _download(session, collection, "open")
    # A download of clear media was made without the option, so its failure is no unplayable attempt.
    assert _stop_unplayable_retry(session, download.id) is False
    assert _mark_drm_protected(session, download.id) == _TRY_UNPLAYABLE
    assert download.media.drm_protected is True
    assert not download.automatic_retry_suppressed

    collection.ytdlp_options = ""
    assert _mark_drm_protected(session, download.id) is True
    assert download.automatic_retry_suppressed is True
