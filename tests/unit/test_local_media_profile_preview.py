from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.endpoints.local_media_profiles import preview
from backend.api.models.local_media_profile_preview import LocalMediaProfilePreviewRequest
from backend.db.models import Episode, Movie, MovieExtra
from backend.services import collection_assets
from backend.utils import output_template
from config.settings.submodels import FilenameRestrictionMode


class _ReadOnlySession:
    no_autoflush = nullcontext()

    def __init__(self, records):
        self.records = records

    def get(self, model, identity):
        return self.records.get((model, identity))

    def commit(self):
        raise AssertionError("A preview must not commit")

    def add(self, _record):
        raise AssertionError("A preview must not persist example values")


@pytest.fixture
def examples(monkeypatch, tmp_path):
    settings = SimpleNamespace(download_settings=SimpleNamespace(
        download_root=tmp_path,
        filename_restriction_mode=FilenameRestrictionMode.WINDOWS,
        download_collection_assets=True,
    ))
    for module in (preview, collection_assets, output_template):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(collection_assets, "collection_profile_roots", lambda *_args, **_kwargs: {})
    collections = [SimpleNamespace(
        id=number, title=f"Saved Show {number}", slug=f"collection-{number}",
        seasons=[SimpleNamespace(slug="season-1", name="First season", index=1, season_number=1)],
        meta_items=[SimpleNamespace(key="custom.folder", value="Saved Folder")],
    ) for number in (1, 2)]
    episodes = [SimpleNamespace(id=number, collection=collection, values={
        "collection": collection.slug, "collection_title": collection.title,
        "title": f"Episode {number}", "episode_title": f"Episode {number}",
        "episode": f"episode-{number}", "episode_label": str(number),
        "season": "season-1", "season_name": "First season", "season_index": "1", "season_number": "1",
        "episode_type": "ep", "year": "2026", "meta_collection_folder": "Saved Folder",
    }) for number, collection in enumerate(collections, 1)]
    movie = SimpleNamespace(id=3, values={"movie_title": "Saved Movie", "title": "Saved Movie"})
    extra = SimpleNamespace(id=4, movie=movie, values={"movie_title": "Saved Movie", "title": "Trailer"})
    records = {(Episode, episode.id): episode for episode in episodes}
    records.update({(Movie, 3): movie, (MovieExtra, 4): extra})
    session = _ReadOnlySession(records)
    monkeypatch.setattr(preview, "episode_output_template_values", lambda episode: dict(episode.values))
    monkeypatch.setattr(preview, "movie_output_template_values", lambda movie, extra=None: dict((extra or movie).values))
    # This unit suite isolates source resolution from custom-index DB traversal,
    # but uses the real renderer, sandbox, root analyzer and filename policy.
    renderer = preview.get_output_template_preview
    monkeypatch.setattr(preview, "get_output_template_preview", lambda _session, body: renderer(None, body))
    return SimpleNamespace(session=session, episodes=episodes, collections=collections, root=tmp_path, settings=settings)


def _body(**overrides):
    return LocalMediaProfilePreviewRequest(**{
        "type": "collection",
        "source_id": "episode:1",
        "output_template": "/downloads/TV/{{ collection_title }}/Season {{ season_number }}/{{ title }}.ext",
        "preferred_format": "format_1080p",
        **overrides,
    })


def test_edited_values_drive_both_paths_without_mutating_source(examples):
    before = deepcopy(examples.episodes[0].values)
    body = _body(values={"collection_title": "Edited Show", "season_number": "9", "title": "Edited Episode"})
    result = preview.get_local_media_profile_preview(examples.session, body)
    assert result.output.output_path == str(examples.root / "TV/Edited Show/Season 9/Edited Episode.mp4")
    assert result.collection_root.path == str(examples.root / "TV/Edited Show")
    assert result.collection_root.collection_title == "Edited Show"
    assert result.output.error is None
    assert result.collection_root.reason is None
    assert examples.episodes[0].values == before
    assert examples.collections[0].title == "Saved Show 1"
    assert body.values == {"collection_title": "Edited Show", "season_number": "9", "title": "Edited Episode"}
    # A later production resolution still uses the saved title, not the edit.
    actual = collection_assets.resolve_collection_media_directory(examples.collections[0], body.output_template)
    assert actual.path == str(examples.root / "TV/Saved Show 1")


def test_a_collection_directory_is_worked_out_once_until_what_decides_it_changes(examples, monkeypatch):
    """The artwork task asks for every collection's directory each time it places a file."""
    template = "/downloads/Asked Often/{{ collection_title }}/{{ title }}.ext"
    analysed = []
    real = collection_assets.infer_collection_media_directory

    def counting(*args, **kwargs):
        analysed.append(args[1]["collection_title"])
        return real(*args, **kwargs)

    monkeypatch.setattr(collection_assets, "infer_collection_media_directory", counting)
    collection = examples.collections[0]

    for _ in range(3):
        assert collection_assets.resolve_collection_media_directory(collection, template).path == str(
            examples.root / "Asked Often/Saved Show 1"
        )
    collection.title = "Renamed Show"
    assert collection_assets.resolve_collection_media_directory(collection, template).path == str(
        examples.root / "Asked Often/Renamed Show"
    )

    assert analysed == ["Saved Show 1", "Renamed Show"]


@pytest.mark.parametrize("folder,expected", [("New Folder", "New Folder"), ("", "Edited Show")])
def test_custom_metadata_overrides_and_empty_fallbacks(examples, folder, expected):
    template = "/downloads/TV/{% if meta_collection_folder %}{{ meta_collection_folder }}{% else %}{{ collection_title }}{% endif %}/{{ title }}.ext"
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template=template, values={"meta_collection_folder": folder, "collection_title": "Edited Show"},
    ))
    assert result.collection_root.path == str(examples.root / "TV" / expected)
    assert Path(result.output.output_path).parent == Path(result.collection_root.path)
    assert examples.collections[0].meta_items[0].value == "Saved Folder"


@pytest.mark.parametrize("source,expected", [("episode:1", "Saved Show 1"), ("episode:2", "Saved Show 2"), ("example:collection", "Example Show"), (None, "Example Show")])
def test_selection_and_fallback_share_one_example(examples, source, expected):
    result = preview.get_local_media_profile_preview(examples.session, _body(source_id=source))
    assert result.collection_root.path == str(examples.root / "TV" / expected)
    assert Path(result.output.output_path).is_relative_to(Path(result.collection_root.path))


def test_both_paths_use_identical_filename_sanitization(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        values={"collection_title": "My/Show: Why?", "title": "A/B?"},
    ))
    assert result.collection_root.path == str(examples.root / "TV/My⧸Show： Why？")
    assert result.output.output_path == str(examples.root / "TV/My⧸Show： Why？/Season 1/A⧸B？.mp4")


def test_edited_season_name_is_a_static_boundary(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template="/downloads/TV/{{ collection_title }}/Custom Season/{{ title }}.ext",
        values={"season_name": "Custom Season"},
    ))
    assert result.collection_root.path == str(examples.root / "TV/Saved Show 1")


def test_filename_error_does_not_hide_valid_root_or_editable_fields(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template="/downloads/TV/{{ collection_title }}/{{ title | regex_replace('a') }}.ext",
    ))
    assert result.output.output_path is None
    assert "replacement" in result.output.error
    assert "title" in result.output.used_variables
    assert result.collection_root.path == str(examples.root / "TV/Saved Show 1")


def test_ambiguous_root_does_not_hide_valid_episode_path(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template="/downloads/{% if episode_type == 'aux' %}Extras{% else %}Shows{% endif %}/{{ collection_title }}/{{ title }}.ext",
    ))
    assert result.output.output_path == str(examples.root / "Shows/Saved Show 1/Episode 1.mp4")
    assert result.collection_root.path is None
    assert result.collection_root.reason


@pytest.mark.parametrize("template", ["/downloads/{{ collection_title }/{{ title }}.ext", "/outside/{{ collection_title }}/{{ title }}.ext"])
def test_invalid_templates_return_both_diagnostics(examples, template):
    result = preview.get_local_media_profile_preview(examples.session, _body(output_template=template))
    assert result.output.output_path is None
    assert result.output.error
    assert result.collection_root.path is None
    assert result.collection_root.reason


@pytest.mark.parametrize("source", ["episode:999", "movie:3", "episode:0", "episode:no", "example:movie", "episode:\u00b2"])
def test_missing_or_wrong_source_does_not_mix_in_fallback_values(examples, source):
    result = preview.get_local_media_profile_preview(examples.session, _body(source_id=source))
    assert result.output.output_path is None
    assert result.output.error
    assert result.collection_root.path is None
    assert result.collection_root.reason == result.output.error


@pytest.mark.parametrize("source,title", [("movie:3", "Saved Movie"), ("movie-extra:4", "Trailer"), ("example:movie", "Example Movie")])
def test_generic_endpoint_supports_movies_and_extras(examples, source, title):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        type="movie", source_id=source,
        output_template="/downloads/Movies/{{ movie_title }}/{{ title }}.ext",
        values={"movie_title": "Edited Movie"},
    ))
    assert result.output.output_path == str(examples.root / "Movies/Edited Movie" / f"{title}.mp4")
    assert result.collection_root is None


def test_index_diagnostics_are_preserved(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template="/downloads/{{ collection_title }}/{{ 'order' | custom_index }}-{{ 'missing' | custom_index }}.ext",
        indexing_values=[{"key": "order", "name": "Order"}],
    ))
    assert result.output.used_indexing_values == ["missing", "order"]
    assert result.output.missing_indexing_values == ["missing"]
    assert result.output.provisional_indexing_values == ["order"]
    assert result.collection_root.path == str(examples.root / "Saved Show 1")


def test_edited_root_collision_keeps_media_preview(examples, monkeypatch):
    monkeypatch.setattr(collection_assets, "collection_profile_roots", lambda *_args, **_kwargs: {
        (2, 10): collection_assets.CollectionMediaDirectory(str(examples.root / "TV/Edited")),
    })
    result = preview.get_local_media_profile_preview(examples.session, _body(values={"collection_title": "Edited"}))
    assert result.output.output_path
    assert result.collection_root.path is None
    assert "another collection" in result.collection_root.reason


def test_generic_http_contract_and_validation(examples, monkeypatch):
    @contextmanager
    def session():
        yield examples.session

    monkeypatch.setattr(preview, "db_session", session)
    app = FastAPI()
    app.include_router(preview.router, prefix="/local-media-profiles")
    with TestClient(app) as client:
        response = client.post("/local-media-profiles/preview", json={
            "type": "collection", "sourceId": "episode:1", "preferredFormat": "format_1080p",
            "outputTemplate": "/downloads/{{ collection_title }}/{{ title }}.ext",
            "values": {"collection_title": "HTTP Example"},
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["collectionRoot"]["path"] == str(examples.root / "HTTP Example")
        assert payload["output"]["outputPath"] == str(examples.root / "HTTP Example/Episode 1.mp4")
        assert payload["collectionRoot"]["systemEnabled"] is True
        invalid = client.post("/local-media-profiles/preview", json={
            "type": "collection", "preferredFormat": "format_1080p", "outputTemplate": "x", "values": [],
        })
        assert invalid.status_code == 422
        assert client.post("/local-media-profiles/template/preview", json={}).status_code == 404
        assert client.post("/local-media-profiles/template/collection-root", json={}).status_code == 404



def test_item_specific_directory_segment_has_no_shared_collection_root(examples):
    result = preview.get_local_media_profile_preview(examples.session, _body(
        output_template="/downloads/shows/{{ episode }}{{ collection_title }}/{{ season_name }}/{{ episode_title }}.ext",
    ))

    assert result.output.output_path == str(
        examples.root / "shows/episode-1Saved Show 1/First season/Episode 1.mp4"
    )
    assert result.collection_root.path is None
    assert "No shared collection-specific directory" in result.collection_root.reason
