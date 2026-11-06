from __future__ import annotations

from conftest import available_artifact, mark_artifact_available, use_database
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    import backend.db.models  # noqa: F401
    from backend.db import Base
    from config import get_settings

    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    use_database(engine)
    session = Session(engine)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    yield session
    session.close()
    engine.dispose()


def _make_collection(session, *, slug="index-collection"):
    from backend.db.models import Collection
    from backend.types.collection_types import EpisodeIdentifier, CollectionType

    collection = Collection(
        source_key="dailywire",
        uuid=f"{slug}-uuid",
        slug=slug,
        title="Index Show",
        description="Description",
        sharing_url=f"https://example.test/{slug}",
        membership_level="FREE",
        type=CollectionType.PODCAST.value,
        episode_identifier=EpisodeIdentifier.NUMBERED.value,
        author_name="Host",
        author_slug="host",
    )
    session.add(collection)
    session.flush()
    return collection


def _make_season(session, collection):
    from backend.db.models import Season

    season = Season(collection=collection, index=1, slug="season-1", name="One")
    session.add(season)
    session.flush()
    return season


def _make_episode(session, collection, season, *, index: int, slug: str, identifier: str):
    from backend.db.models import Episode
    from backend.utils.helpers import generate_uuid

    episode = Episode(
        source_key="dailywire",
        uuid=generate_uuid(),
        type="episode",
        collection=collection,
        season=season,
        index=index,
        episode_identifier=identifier,
        slug=slug,
        title=slug.replace("-", " ").title(),
        duration=100.0,
        publish_status="published_final",
        sharing_url=f"https://example.test/{slug}",
        published_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    session.add(episode)
    session.flush()
    return episode


def _make_profile(session, *, template: str):
    from backend.db.models import CollectionLocalMediaProfile

    profile = CollectionLocalMediaProfile(
        slug="indexed-video",
        name="Indexed video",
        output_template=template,
        preferred_format="format_1080p",
        collection_scope="both",
    )
    session.add(profile)
    session.flush()
    return profile


def _make_download(session, episode, profile, *, file_path=""):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType

    download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=episode.id,
        local_media_profile_id=profile.id,
        artifact_status=MediaDownloadArtifactStatus.ABSENT.value,
        file_path=file_path,
    )
    session.add(download)
    session.flush()
    return download


def _define(profile, *definitions: tuple[str, str]):
    from backend.utils.custom_index import IndexingValueDefinition, replace_indexing_value_definitions

    replace_indexing_value_definitions(
        profile,
        [IndexingValueDefinition(key=key, name=name) for key, name in definitions],
    )


def _request(session, collection, profile):
    from backend.db.models import CustomIndexState
    state = session.query(CustomIndexState).filter_by(collection_id=collection.id, local_media_profile_id=profile.id).one_or_none()
    if state is None:
        state = CustomIndexState(collection_id=collection.id, local_media_profile_id=profile.id)
        session.add(state)
    else:
        state.requested_generation += 1
    session.flush()
    return state


def test_episode_downloads_for_same_collection_profile_run_concurrently(tmp_path, monkeypatch):
    from config import get_settings
    from task_manager.scheduler.results import TaskResult
    from task_manager.tasks.workers.download_episode import entrypoint

    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)

    class FakeSession:
        def get(self, model, resource_id):
            if model is entrypoint.EpisodeMediaDownload:
                return SimpleNamespace(media_item_id=100, local_media_profile_id=200)
            if model is entrypoint.Episode:
                return SimpleNamespace(collection_id=300)
            raise AssertionError(f"Unexpected model lookup: {model}")

        def commit(self):
            pass

    @contextmanager
    def fake_db_session():
        yield FakeSession()

    async def ready(*_args, **_kwargs):
        return None

    monkeypatch.setattr(entrypoint, "db_session", fake_db_session)
    monkeypatch.setattr(entrypoint, "wait_for_custom_index_pair", ready)
    monkeypatch.setattr(entrypoint, "pair_is_ready", lambda *_args: True)
    monkeypatch.setattr(entrypoint, "request_collection_asset_reconciliation", lambda *_args: None)

    async def exercise():
        both_started = asyncio.Event()
        release = asyncio.Event()
        started = 0

        async def fake_run_download_episode(
            _session,
            *,
            media_download_id,
            is_redownload=False,
            prepare_existing_artifact=False,
            progress=None,
        ):
            nonlocal started
            started += 1
            if started == 2:
                both_started.set()
            await release.wait()
            return TaskResult(summary=f"Downloaded {media_download_id}")

        monkeypatch.setattr(entrypoint, "run_download_episode", fake_run_download_episode)

        first = asyncio.create_task(entrypoint.download_episode(resource_id=1))
        second = asyncio.create_task(entrypoint.download_episode(resource_id=2))
        try:
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
        finally:
            release.set()
        await asyncio.gather(first, second)

    asyncio.run(exercise())


def test_definitions_belong_to_lmp_and_serialize(db_session):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIRead
    from backend.utils.custom_index import get_indexing_value_definitions
    collection = _make_collection(db_session)
    profile = _make_profile(db_session, template="/downloads/{{ episode }}.ext")
    _define(profile, ("featurettes", "Featurettes"))
    db_session.flush()
    assert get_indexing_value_definitions(collection) == []
    assert [(value.key, value.name) for value in CollectionLocalMediaProfileAPIRead.model_validate(profile).indexing_values] == [("featurettes", "Featurettes")]


def test_custom_index_keys_allow_dashes_end_to_end(db_session):
    from backend.api.models.custom_metadata import IndexingValueDefinitionAPI
    from backend.utils.custom_index import get_indexing_value_definitions
    from backend.utils.output_template import output_template_custom_index_keys

    definition = IndexingValueDefinitionAPI(
        key="behind-the-scenes",
        name="Behind the scenes",
    )
    template = "/downloads/{{ 'behind-the-scenes' | custom_index }}.ext"
    profile = _make_profile(db_session, template=template)
    _define(profile, (definition.key, definition.name))

    assert [(value.key, value.name) for value in get_indexing_value_definitions(profile)] == [
        ("behind-the-scenes", "Behind the scenes"),
    ]
    assert output_template_custom_index_keys(template) == {"behind-the-scenes"}


def test_custom_index_requires_literal_key():
    from backend.utils.output_template import output_template_custom_index_keys
    assert output_template_custom_index_keys("/downloads/{{ 'featurettes' | custom_index }}.ext") == {"featurettes"}
    with pytest.raises(ValueError, match="literal key"):
        output_template_custom_index_keys("/downloads/{{ episode_type | custom_index }}.ext")


def test_conditional_paths_can_select_distinct_index_directories():
    from backend.utils.output_template import (
        COLLECTION_OUTPUT_TEMPLATE_FIELDS, COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
        validate_output_template_path_requirements,
    )

    template = ("{% if episode_type == 'trailer' %}"
                "{% set number = 'extras' | custom_index %}"
                "/downloads/Extras/{{ number }}.ext"
                "{% else %}"
                "{% set number = 'featurettes' | custom_index %}"
                "/downloads/Featurettes/{{ number }}.ext"
                "{% endif %}")
    assert validate_output_template_path_requirements(
        template, allowed_fields=COLLECTION_OUTPUT_TEMPLATE_FIELDS,
        allowed_metadata_scopes=COLLECTION_OUTPUT_TEMPLATE_METADATA_SCOPES,
    ) == template


def test_reconciliation_uses_every_episode_and_reorders_historical_discovery(db_session):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import get_episode_index_assignments
    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    profile = _make_profile(db_session, template="/downloads/{{ 'featurettes' | custom_index }}-{{ episode }}.ext")
    _define(profile, ("featurettes", "Featurettes"))
    first = _make_episode(db_session, collection, season, index=100, slug="first", identifier="ep.1")
    last = _make_episode(db_session, collection, season, index=300, slug="last", identifier="ep.3")
    download = _make_download(db_session, last, profile)
    state = _request(db_session, collection, profile)
    result = reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    db_session.flush()
    assert result.episodes_considered == 2
    assert get_episode_index_assignments(first, profile.id) == {"featurettes": 1}
    assert get_episode_index_assignments(last, profile.id) == {"featurettes": 2}
    assert not any(item.key.startswith("custom_index.") for item in download.meta_items)
    assert state.completed_generation == state.requested_generation

    middle = _make_episode(db_session, collection, season, index=200, slug="middle", identifier="ep.2")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert get_episode_index_assignments(middle, profile.id) == {"featurettes": 2}
    assert get_episode_index_assignments(last, profile.id) == {"featurettes": 3}
    again = reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert again.assignments_changed == 0


def test_branches_repeated_calls_and_undefined_key(db_session):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import get_episode_index_assignments
    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    template = """{% if episode_type == 'trailer' %}{% set a = 'featurettes' | custom_index %}{% set b = 'featurettes' | custom_index %}/downloads/{{ a }}-{{ episode }}.ext{% else %}{% set a = 'extras' | custom_index %}{% set missing = 'unknown' | custom_index %}/downloads/{{ a }}-{{ episode }}.ext{% endif %}"""
    profile = _make_profile(db_session, template=template)
    _define(profile, ("featurettes", "Featurettes"), ("extras", "Extras"))
    trailer = _make_episode(db_session, collection, season, index=100, slug="trailer", identifier="aux.1")
    featurette = _make_episode(db_session, collection, season, index=200, slug="featurette", identifier="trailer.1")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert get_episode_index_assignments(trailer, profile.id) == {"extras": 1}
    assert get_episode_index_assignments(featurette, profile.id) == {"featurettes": 1}


def test_removed_definition_and_scope_clean_all_assignments(db_session):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import get_episode_index_assignments
    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ 'extras' | custom_index }}.ext")
    _define(profile, ("extras", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert get_episode_index_assignments(episode, profile.id) == {"extras": 1}
    _define(profile)
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert get_episode_index_assignments(episode, profile.id) == {}
    _define(profile, ("extras", "Extras"))
    profile.collection_scope = "series"
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert get_episode_index_assignments(episode, profile.id) == {}


def test_normal_render_requires_current_generation_and_never_allocates(db_session):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import CustomIndexNotReadyError, get_episode_index_assignments
    from backend.utils.output_template import resolve_episode_output_path
    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext")
    _define(profile, ("extras", "Extras"))
    state = _request(db_session, collection, profile)
    with pytest.raises(CustomIndexNotReadyError):
        resolve_episode_output_path(profile.output_template, episode=episode, local_media_profile=profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    before = get_episode_index_assignments(episode, profile.id)
    assert str(resolve_episode_output_path(profile.output_template, episode=episode, local_media_profile=profile)).endswith("1-first.ext")
    assert get_episode_index_assignments(episode, profile.id) == before
    state.requested_generation += 1
    db_session.flush()
    with pytest.raises(CustomIndexNotReadyError):
        resolve_episode_output_path(profile.output_template, episode=episode, local_media_profile=profile)


def test_undefined_index_renders_empty_without_sequence_state(db_session):
    from backend.db.models import CustomIndexState
    from backend.utils.output_template import resolve_episode_output_path

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ 'undefined' | custom_index }}-{{ episode }}.ext")
    assert str(resolve_episode_output_path(
        profile.output_template, episode=episode, local_media_profile=profile,
    )).endswith("-first.ext")
    assert db_session.query(CustomIndexState).count() == 0
    assert episode.meta_items == []


def test_profile_save_queues_index_work_before_optional_rename(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from backend.db.models import CustomIndexState
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ episode }}.ext")
    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name, preferred_format=profile.preferred_format,
        output_template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext",
        collection_scope="both", indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(db_session, profile.slug, body, rename_files=True)

    operations = list(db_session.query(TaskOperation).all())
    assert [operation.kind for operation in operations] == ["local_media_profile.manage_custom_indexes"]
    assert operations[0].targets[0].task_kwargs["rename_after"] is True
    state = db_session.query(CustomIndexState).one()
    assert (state.collection_id, state.local_media_profile_id) == (collection.id, profile.id)
    assert state.completed_generation < state.requested_generation


def test_draft_preview_simulates_without_persisting(db_session):
    from backend.api.endpoints.local_media_profiles.output_template import get_output_template_preview
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.utils.custom_index import get_episode_index_assignments
    from backend.utils.output_template import episode_output_template_values
    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    first = _make_episode(db_session, collection, season, index=100, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=200, slug="second", identifier="ep.2")
    profile = _make_profile(db_session, template="/downloads/{{ episode }}.ext")
    body = LocalMediaProfileTemplatePreview(type="collection", output_template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext", preferred_format="format_1080p", values=episode_output_template_values(second), source_id=f"episode:{second.id}", local_media_profile_id=profile.id, indexing_values=[{"key": "extras", "name": "Extras"}])
    preview = get_output_template_preview(db_session, body)
    assert preview.output_path.endswith("2-second.mp4")
    assert get_episode_index_assignments(first, profile.id) == {}
    assert get_episode_index_assignments(second, profile.id) == {}


@pytest.mark.parametrize("was_synchronized", [True, False])
def test_historical_episode_only_queues_rename_for_synchronized_file(db_session, was_synchronized):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.utils.output_template import resolve_episode_output_path

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    profile = _make_profile(db_session, template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext")
    _define(profile, ("extras", "Extras"))
    _make_episode(db_session, collection, season, index=100, slug="first", identifier="ep.1")
    last = _make_episode(db_session, collection, season, index=300, slug="last", identifier="ep.3")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    expected = resolve_episode_output_path(
        profile.output_template, episode=last, local_media_profile=profile, extension="mp4",
    )
    source = expected if was_synchronized else expected.with_name("kept-by-user.mp4")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"video")
    download = _make_download(db_session, last, profile, file_path=str(source))
    mark_artifact_available(download)
    db_session.flush()

    _make_episode(db_session, collection, season, index=200, slug="middle", identifier="ep.2")
    _request(db_session, collection, profile)
    result = reconcile_collection_profile_custom_indexes(
        db_session, collection_id=collection.id, local_media_profile_id=profile.id,
    )
    assert result.synced_source_paths == (
        ((last.id, str(expected)),) if was_synchronized else ()
    )
    assert source.read_bytes() == b"video"


def test_batch_file_rename_rollback_restores_cycle_without_overwrite(db_session, monkeypatch):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from backend.utils.output_template import resolve_episode_output_path
    from task_manager.tasks.workers.rename_collection_profile_files.service import run_rename_collection_profile_files

    collection = _make_collection(db_session, slug="rollback-collection")
    season = _make_season(db_session, collection)
    profile = _make_profile(
        db_session,
        template="/downloads/{{ collection }}/{{ episode }}.ext",
    )
    first = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=2, slug="second", identifier="ep.2")

    first_expected = resolve_episode_output_path(
        profile.output_template,
        episode=first,
        local_media_profile=profile,
        extension="mp4",
    )
    second_expected = resolve_episode_output_path(
        profile.output_template,
        episode=second,
        local_media_profile=profile,
        extension="mp4",
    )
    first_expected.parent.mkdir(parents=True, exist_ok=True)
    second_expected.write_bytes(b"first episode")
    first_expected.write_bytes(b"second episode")

    first_download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=first.id,
        local_media_profile_id=profile.id,
        **available_artifact(),
        file_path=str(second_expected),
    )
    second_download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=second.id,
        local_media_profile_id=profile.id,
        **available_artifact(),
        file_path=str(first_expected),
    )
    db_session.add_all([first_download, second_download])
    db_session.commit()

    from backend.services import download_relocation

    def fail_to_record(*_args, **_kwargs):
        raise RuntimeError("forced database commit failure")

    # The files are moved, then recording the new paths fails.
    monkeypatch.setattr(download_relocation, "_record_relocations", fail_to_record)
    with pytest.raises(RuntimeError, match="forced database commit failure"):
        run_rename_collection_profile_files(
            collection_id=collection.id,
            local_media_profile_id=profile.id,
        )

    assert first_expected.read_bytes() == b"second episode"
    assert second_expected.read_bytes() == b"first episode"


def test_batch_file_rename_stages_source_destination_cycle(db_session):
    from backend.db.models.media_download import EpisodeMediaDownload
    from backend.types.download_profile_types import MediaDownloadArtifactStatus
    from backend.types.media_types import MediaType
    from backend.utils.output_template import resolve_episode_output_path
    from task_manager.tasks.workers.rename_collection_profile_files.service import run_rename_collection_profile_files

    collection = _make_collection(db_session, slug="rename-collection")
    season = _make_season(db_session, collection)
    profile = _make_profile(
        db_session,
        template="/downloads/{{ collection }}/{{ episode }}.ext",
    )
    first = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=2, slug="second", identifier="ep.2")

    first_expected = resolve_episode_output_path(
        profile.output_template,
        episode=first,
        local_media_profile=profile,
        extension="mp4",
    )
    second_expected = resolve_episode_output_path(
        profile.output_template,
        episode=second,
        local_media_profile=profile,
        extension="mp4",
    )
    first_expected.parent.mkdir(parents=True, exist_ok=True)
    second_expected.write_bytes(b"first episode")
    first_expected.write_bytes(b"second episode")

    first_download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=first.id,
        local_media_profile_id=profile.id,
        **available_artifact(),
        file_path=str(second_expected),
    )
    second_download = EpisodeMediaDownload(
        type=MediaType.EPISODE.value,
        media_item_id=second.id,
        local_media_profile_id=profile.id,
        **available_artifact(),
        file_path=str(first_expected),
    )
    db_session.add_all([first_download, second_download])
    db_session.commit()

    result = run_rename_collection_profile_files(
        collection_id=collection.id,
        local_media_profile_id=profile.id,
    )

    assert result.data["files_renamed"] == 2
    assert first_expected.read_bytes() == b"first episode"
    assert second_expected.read_bytes() == b"second episode"
    db_session.refresh(first_download)
    db_session.refresh(second_download)
    assert first_download.file_path == str(first_expected)
    assert second_download.file_path == str(second_expected)


def test_preview_skips_custom_index_work_when_template_has_no_index(db_session, monkeypatch):
    from backend.api.endpoints.local_media_profiles import output_template as preview_service
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ episode }}.ext")

    monkeypatch.setattr(
        preview_service,
        "simulate_episode_indexes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("simulation should be skipped")),
    )
    preview = preview_service.get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template="/downloads/renamed/{{ episode }}.ext",
            preferred_format="format_1080p",
            values=episode_output_template_values(episode),
            source_id=f"episode:{episode.id}",
            local_media_profile_id=profile.id,
            indexing_values=[],
        ),
    )
    assert preview.output_path.endswith("/renamed/first.mp4")


def test_preview_skips_simulation_when_referenced_index_is_undefined(db_session, monkeypatch):
    from backend.api.endpoints.local_media_profiles import output_template as preview_service
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    profile = _make_profile(db_session, template="/downloads/{{ episode }}.ext")

    monkeypatch.setattr(
        preview_service,
        "simulate_episode_indexes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("simulation should be skipped")),
    )
    preview = preview_service.get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext",
            preferred_format="format_1080p",
            values=episode_output_template_values(episode),
            source_id=f"episode:{episode.id}",
            local_media_profile_id=profile.id,
            indexing_values=[],
        ),
    )
    assert preview.output_path.endswith("/-first.mp4")
    assert preview.missing_indexing_values == ["extras"]


def test_preview_reuses_saved_assignment_for_identical_template_without_analysis(db_session, monkeypatch):
    from backend.api.endpoints.local_media_profiles import output_template as preview_service
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.services import custom_index_preview
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episode = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    template = (
        "{% set n = 'extra' | custom_index %}"
        "{% set unrelated = (' (' ~ episode ~ ')') if episode %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=template)
    _define(profile, ("extra", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(
        db_session,
        collection_id=collection.id,
        local_media_profile_id=profile.id,
    )

    monkeypatch.setattr(
        custom_index_preview,
        "compare_custom_index_reachability",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("identical templates should not require static analysis")
        ),
    )
    monkeypatch.setattr(
        preview_service,
        "simulate_episode_indexes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("saved assignment should be reused")
        ),
    )
    preview = preview_service.get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template=template,
            preferred_format="format_1080p",
            values=episode_output_template_values(episode),
            source_id=f"episode:{episode.id}",
            local_media_profile_id=profile.id,
            indexing_values=[{"key": "extra", "name": "Extras"}],
        ),
    )
    assert preview.output_path.endswith("/1-first.mp4")


def test_preview_reuses_saved_assignment_when_index_reachability_is_unchanged(db_session, monkeypatch):
    from backend.api.endpoints.local_media_profiles import output_template as preview_service
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    first = _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=2, slug="second", identifier="ep.2")
    saved = (
        "{% if episode == 'second' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extras", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)

    monkeypatch.setattr(
        preview_service,
        "simulate_episode_indexes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("saved assignment should be reused")),
    )
    draft = saved.replace("/downloads/", "/downloads/renamed/")
    preview = preview_service.get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template=draft,
            preferred_format="format_1080p",
            values=episode_output_template_values(second),
            source_id=f"episode:{second.id}",
            local_media_profile_id=profile.id,
            indexing_values=[{"key": "extras", "name": "Extras"}],
        ),
    )
    assert preview.output_path.endswith("/renamed/1-second.mp4")
    assert first.id != second.id


def test_preview_simulates_when_index_reachability_changes(db_session):
    from backend.api.endpoints.local_media_profiles.output_template import get_output_template_preview
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=2, slug="second", identifier="ep.2")
    saved = (
        "{% if episode == 'second' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extras", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)

    draft = (
        "{% if episode != 'never' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    preview = get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template=draft,
            preferred_format="format_1080p",
            values=episode_output_template_values(second),
            source_id=f"episode:{second.id}",
            local_media_profile_id=profile.id,
            indexing_values=[{"key": "extras", "name": "Extras"}],
        ),
    )
    assert preview.output_path.endswith("/2-second.mp4")


def test_preview_simulates_when_index_dependency_test_value_changes(db_session):
    from backend.api.endpoints.local_media_profiles.output_template import get_output_template_preview
    from backend.api.models.local_media_profile import LocalMediaProfileTemplatePreview
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.output_template import episode_output_template_values

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    second = _make_episode(db_session, collection, season, index=2, slug="second", identifier="ep.2")
    template = (
        "{% if episode == 'second' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=template)
    _define(profile, ("extras", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)

    values = episode_output_template_values(second)
    values["episode"] = "first"
    preview = get_output_template_preview(
        db_session,
        LocalMediaProfileTemplatePreview(
            type="collection",
            output_template=template,
            preferred_format="format_1080p",
            values=values,
            source_id=f"episode:{second.id}",
            local_media_profile_id=profile.id,
            indexing_values=[{"key": "extras", "name": "Extras"}],
        ),
    )
    assert preview.output_path.endswith("/-first.mp4")


def test_simulation_compiles_the_output_template_once(db_session, monkeypatch):
    from backend.services import custom_indexes
    from backend.utils.output_template import prepare_output_template as real_prepare

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    episodes = [
        _make_episode(db_session, collection, season, index=index, slug=f"episode-{index}", identifier=f"ep.{index}")
        for index in range(1, 5)
    ]
    calls = 0

    def counted_prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(custom_indexes, "prepare_output_template", counted_prepare)
    custom_indexes.simulate_episode_indexes(
        episodes,
        template="/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext",
        definitions=frozenset({"extras"}),
    )
    assert calls == 1


def test_profile_save_skips_index_management_when_assignment_reachability_is_unchanged(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from backend.db.models import CustomIndexState
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    saved = (
        "{% if episode_type == 'aux' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extras", "Extras"))
    state = _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(
        db_session,
        collection_id=collection.id,
        local_media_profile_id=profile.id,
    )
    generation = state.requested_generation

    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=saved.replace("/downloads/", "/downloads/renamed/"),
        collection_scope="both",
        indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(
        db_session,
        profile.slug,
        body,
        rename_files=True,
    )

    operations = list(db_session.query(TaskOperation).order_by(TaskOperation.id))
    assert [operation.kind for operation in operations] == ["local_media_profile.rename_files"]
    db_session.refresh(state)
    assert state.requested_generation == generation
    assert state.completed_generation == generation


def test_profile_save_ignores_unrelated_unsupported_jinja_for_index_management(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    saved = (
        "{% set n = 'extra' | custom_index %}"
        "{% set unrelated = (' (' ~ episode ~ ')') if episode %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extra", "Extras"))

    changed = saved.replace(
        "(' (' ~ episode ~ ')')",
        "(' [' ~ episode ~ ']')",
    )
    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=changed,
        collection_scope="both",
        indexing_values=[{"key": "extra", "name": "Extras"}],
    )
    update_collection_local_media_profile(
        db_session,
        profile.slug,
        body,
        rename_files=True,
    )

    operations = list(db_session.query(TaskOperation).order_by(TaskOperation.id))
    assert [operation.kind for operation in operations] == ["local_media_profile.rename_files"]


def test_profile_save_queues_index_management_when_assignment_reachability_changes(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    saved = (
        "{% if episode_type == 'aux' %}{% set n = 'extras' | custom_index %}"
        "{% else %}{% set n = '' %}{% endif %}"
        "/downloads/{{ n }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extras", "Extras"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(
        db_session,
        collection_id=collection.id,
        local_media_profile_id=profile.id,
    )

    changed = saved.replace("episode_type == 'aux'", "episode_type == 'ep'")
    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=changed,
        collection_scope="both",
        indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(
        db_session,
        profile.slug,
        body,
        rename_files=True,
    )

    operations = list(db_session.query(TaskOperation).order_by(TaskOperation.id))
    assert [operation.kind for operation in operations] == ["local_media_profile.manage_custom_indexes"]
    assert operations[0].targets[0].task_kwargs["rename_after"] is True


def test_profile_save_conservatively_queues_index_management_when_analysis_is_unknown(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    saved = (
        "{% macro number() %}{{ 'extras' | custom_index }}{% endmacro %}"
        "/downloads/{{ number() }}-{{ episode }}.ext"
    )
    profile = _make_profile(db_session, template=saved)
    _define(profile, ("extras", "Extras"))

    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=saved.replace("/downloads/", "/downloads/renamed/"),
        collection_scope="both",
        indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(db_session, profile.slug, body)

    operations = list(db_session.query(TaskOperation).order_by(TaskOperation.id))
    assert [operation.kind for operation in operations] == ["local_media_profile.manage_custom_indexes"]


def test_profile_save_scope_change_still_queues_index_management(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    template = "/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext"
    profile = _make_profile(db_session, template=template)
    _define(profile, ("extras", "Extras"))

    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=template,
        collection_scope="podcast",
        indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(db_session, profile.slug, body)

    operations = list(db_session.query(TaskOperation).order_by(TaskOperation.id))
    assert [operation.kind for operation in operations] == ["local_media_profile.manage_custom_indexes"]


def test_profile_save_unused_definition_change_does_not_queue_index_management(db_session):
    from backend.api.endpoints.collection_local_media_profiles.service import update_collection_local_media_profile
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate
    from task_manager.scheduler.db import TaskOperation

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    _make_episode(db_session, collection, season, index=1, slug="first", identifier="ep.1")
    template = "/downloads/{{ 'extras' | custom_index }}-{{ episode }}.ext"
    profile = _make_profile(db_session, template=template)
    _define(profile, ("extras", "Extras"), ("unused", "Unused"))

    body = CollectionLocalMediaProfileAPIUpdate(
        name=profile.name,
        preferred_format=profile.preferred_format,
        output_template=template,
        collection_scope="both",
        indexing_values=[{"key": "extras", "name": "Extras"}],
    )
    update_collection_local_media_profile(db_session, profile.slug, body)

    assert not any(
        operation.kind == "local_media_profile.manage_custom_indexes"
        for operation in db_session.query(TaskOperation)
    )


def _keep(profile, *definitions: tuple[str, str]):
    from backend.utils.custom_index import IndexingValueDefinition, replace_indexing_value_definitions

    replace_indexing_value_definitions(
        profile,
        [IndexingValueDefinition(key=key, name=name, keep_numbers=True) for key, name in definitions],
    )


def test_per_start_and_step_number_each_group_on_its_own(db_session):
    from backend.db.models import Season
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import get_episode_index_assignments
    from backend.utils.output_template import (
        resolve_episode_output_path_with_index_values,
    )

    collection = _make_collection(db_session)
    one = _make_season(db_session, collection)
    two = Season(collection=collection, index=2, slug="season-2", name="Two")
    db_session.add(two)
    db_session.flush()
    template = "/downloads/{{ 'clips' | custom_index(per=season_index, start=0, step=10) }}-{{ episode }}.ext"
    profile = _make_profile(db_session, template=template)
    _define(profile, ("clips", "Clips"))
    a = _make_episode(db_session, collection, one, index=100, slug="a", identifier="ep.1")
    b = _make_episode(db_session, collection, two, index=200, slug="b", identifier="ep.2")
    c = _make_episode(db_session, collection, one, index=300, slug="c", identifier="ep.3")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)

    assert [get_episode_index_assignments(item, profile.id) for item in (a, b, c)] == [
        {"clips": 1}, {"clips": 1}, {"clips": 2},
    ]
    path = resolve_episode_output_path_with_index_values(
        template, episode=c, index_definitions=frozenset({"clips"}),
        index_values=get_episode_index_assignments(c, profile.id),
    )
    assert path.name.startswith("10-")


@pytest.mark.parametrize(("template", "message"), [
    ("{{ 'clips' | custom_index(2) }}", "only takes"),
    ("{{ 'clips' | custom_index(every=2) }}", "no every= argument"),
    ("{{ 'clips' | custom_index(start='1') }}", "whole number"),
    ("{{ 'clips' | custom_index(step=season_index) }}", "whole number"),
    ("{{ 'clips' | custom_index(step=0) }}", "cannot be 0"),
    ("{{ 'clips' | custom_index(per='x' | custom_index) }}", "another Custom Index"),
    ("{{ 'clips' | custom_index(per=title | random) }}", "random filter"),
    ("{{ 'clips' | custom_index(per=title.upper()) }}", "not by calls"),
])
def test_custom_index_arguments_are_checked(template, message):
    from backend.utils.output_template import output_template_custom_index_keys

    with pytest.raises(ValueError, match=message):
        output_template_custom_index_keys(f"/downloads/{template}.ext")


def test_custom_index_accepts_negative_start_and_list_groups():
    from backend.utils.output_template import output_template_custom_index_calls

    calls = output_template_custom_index_calls(
        "/downloads/{{ 'clips' | custom_index(per=[season_index, episode_type], start=-1, step=-1) }}.ext"
    )
    assert calls == {"clips": frozenset({"[season_index, episode_type]"})}


def test_kept_numbers_stay_and_new_episodes_take_the_next_number(db_session):
    from backend.services.custom_indexes import reconcile_collection_profile_custom_indexes
    from backend.utils.custom_index import get_episode_index_assignments, kept_index_keys

    collection = _make_collection(db_session)
    season = _make_season(db_session, collection)
    profile = _make_profile(db_session, template="/downloads/{{ 'clips' | custom_index }}-{{ episode }}.ext")
    _keep(profile, ("clips", "Clips"))
    assert kept_index_keys(profile) == {"clips"}
    first = _make_episode(db_session, collection, season, index=100, slug="first", identifier="ep.1")
    last = _make_episode(db_session, collection, season, index=300, slug="last", identifier="ep.3")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)

    middle = _make_episode(db_session, collection, season, index=200, slug="middle", identifier="ep.2")
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert [get_episode_index_assignments(item, profile.id) for item in (first, middle, last)] == [
        {"clips": 1}, {"clips": 3}, {"clips": 2},
    ]

    # Without keep, the numbers follow episode order again.
    _define(profile, ("clips", "Clips"))
    _request(db_session, collection, profile)
    reconcile_collection_profile_custom_indexes(db_session, collection_id=collection.id, local_media_profile_id=profile.id)
    assert [get_episode_index_assignments(item, profile.id) for item in (first, middle, last)] == [
        {"clips": 1}, {"clips": 2}, {"clips": 3},
    ]


def test_kept_numbers_continue_within_their_own_group(db_session):
    from backend.db.models import Season
    from backend.services.custom_indexes import simulate_episode_indexes

    collection = _make_collection(db_session)
    one = _make_season(db_session, collection)
    two = Season(collection=collection, index=2, slug="season-2", name="Two")
    db_session.add(two)
    db_session.flush()
    a = _make_episode(db_session, collection, one, index=100, slug="a", identifier="ep.1")
    b = _make_episode(db_session, collection, two, index=200, slug="b", identifier="ep.2")
    c = _make_episode(db_session, collection, one, index=300, slug="c", identifier="ep.3")
    desired = simulate_episode_indexes(
        [a, b, c],
        template="/downloads/{{ 'clips' | custom_index(per=season_index) }}-{{ episode }}.ext",
        definitions=frozenset({"clips"}),
        kept={a.id: {"clips": 5}},
        keep_keys=frozenset({"clips"}),
    )
    assert desired == {a.id: {"clips": 5}, b.id: {"clips": 1}, c.id: {"clips": 6}}


@pytest.mark.parametrize(("change", "status"), [
    ("start", "unchanged"),
    ("per", "changed"),
    ("keep", "changed"),
])
def test_grouping_and_keeping_change_assignments_but_start_does_not(change, status):
    from backend.services.custom_indexes import compare_custom_index_assignments

    saved = "/downloads/{{ 'clips' | custom_index }}.ext"
    template = {
        "start": "/downloads/{{ 'clips' | custom_index(start=0) }}.ext",
        "per": "/downloads/{{ 'clips' | custom_index(per=season_index) }}.ext",
        "keep": saved,
    }[change]
    result = compare_custom_index_assignments(
        saved, template,
        previous_definition_keys=frozenset({"clips"}),
        current_definition_keys=frozenset({"clips"}),
        current_kept_keys=frozenset({"clips"}) if change == "keep" else frozenset(),
    )
    assert result.status.value == status


def test_keep_numbers_round_trips_through_the_api(db_session):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIRead

    profile = _make_profile(db_session, template="/downloads/{{ 'clips' | custom_index }}.ext")
    _keep(profile, ("clips", "Clips"))
    db_session.flush()
    read = CollectionLocalMediaProfileAPIRead.model_validate(profile)
    assert [(item.key, item.keep_numbers) for item in read.indexing_values] == [("clips", True)]
