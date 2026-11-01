from types import SimpleNamespace

import pytest

from backend.services import collection_assets as assets
from backend.utils.collection_media_directory import CollectionMediaDirectory


@pytest.mark.parametrize('system,override,expected', [
    (False, None, False), (True, None, True),
    (False, True, True), (True, False, False),
    (False, False, False), (True, True, True),
])
def test_profile_override_inherits_only_when_null(monkeypatch, system, override, expected):
    monkeypatch.setattr(assets, 'get_settings', lambda: SimpleNamespace(
        download_settings=SimpleNamespace(download_collection_assets=system),
    ))
    assert assets.collection_assets_enabled(SimpleNamespace(download_collection_assets=override)) is expected


def test_artwork_source_priorities_and_missing_variants():
    collection = SimpleNamespace(
        thumbnail_portrait_path='https://example.invalid/portrait',
        thumbnail_square_path='https://example.invalid/square',
        thumbnail_landscape_path='https://example.invalid/landscape',
        background_image_path='https://example.invalid/background',
        logo_image_path='https://example.invalid/logo',
    )
    assert {
        source.kind: (source.url, source.forced_format)
        for source in assets.collection_asset_sources(collection)
    } == {
        'poster': (collection.thumbnail_portrait_path, None),
        'fanart': (collection.background_image_path, None),
        'square': (collection.thumbnail_square_path, None),
        'clearlogo': (collection.logo_image_path, 'png'),
    }
    collection.thumbnail_portrait_path = None
    collection.background_image_path = None
    source_map = {source.kind: source.url for source in assets.collection_asset_sources(collection)}
    assert source_map['poster'] == collection.thumbnail_square_path
    assert source_map['fanart'] == collection.thumbnail_landscape_path
    collection.thumbnail_square_path = None
    collection.thumbnail_landscape_path = 'file:///not-a-remote-image'
    collection.logo_image_path = None
    assert assets.collection_asset_sources(collection) == ()


def test_artwork_metadata_refresh_preserves_absent_variants():
    collection = SimpleNamespace(thumbnail_portrait_path='old', thumbnail_square_path='known-square')
    assets.update_collection_artwork_metadata(collection, SimpleNamespace(thumbnail_portrait_path='new'))
    assert collection.thumbnail_portrait_path == 'new'
    assert collection.thumbnail_square_path == 'known-square'


def test_preview_uses_selected_episodes_collection_and_unsaved_template(monkeypatch):
    collection = SimpleNamespace(id=7, title='Actual collection')
    session = SimpleNamespace(get=lambda _model, identity: SimpleNamespace(collection=collection) if identity == 42 else None)
    monkeypatch.setattr(assets, 'get_settings', lambda: SimpleNamespace(
        download_settings=SimpleNamespace(download_collection_assets=True),
    ))
    received = []

    def resolve(actual_collection, template, *, values_overrides=None):
        received.append((actual_collection, template))
        return CollectionMediaDirectory('/library/Actual collection')

    monkeypatch.setattr(assets, 'resolve_collection_media_directory', resolve)
    monkeypatch.setattr(assets, 'collection_profile_roots', lambda _session, **kwargs: {})
    result = assets.get_collection_asset_root_preview(
        session, source_id='episode:42', output_template='unsaved-template', local_media_profile_id=None,
    )
    assert received == [(collection, 'unsaved-template')]
    assert result.path == '/library/Actual collection'
    assert result.collection_title == 'Actual collection'
    assert result.system_enabled is True
    assert assets.get_collection_asset_root_preview(
        session, source_id='example', output_template='unsaved-template', local_media_profile_id=None,
    ).path is None
    assert assets.get_collection_asset_root_preview(
        session, source_id='episode:99', output_template='unsaved-template', local_media_profile_id=None,
    ).path is None


def test_preview_rejects_another_collections_root_but_allows_same_collection_profiles(monkeypatch):
    monkeypatch.setattr(assets, 'get_settings', lambda: SimpleNamespace(
        download_settings=SimpleNamespace(download_collection_assets=False),
    ))
    session = SimpleNamespace(get=lambda *_args: SimpleNamespace(collection=SimpleNamespace(id=1, title='First')))
    monkeypatch.setattr(assets, 'resolve_collection_media_directory', lambda *_args, **_kwargs: CollectionMediaDirectory('/library/shared'))
    roots = {(1, 2): CollectionMediaDirectory('/library/shared')}
    monkeypatch.setattr(assets, 'collection_profile_roots', lambda *_args, **_kwargs: roots)
    arguments = dict(source_id='episode:42', output_template='draft', local_media_profile_id=2)
    assert assets.get_collection_asset_root_preview(session, **arguments).path == '/library/shared'
    roots[2, 3] = CollectionMediaDirectory('/library/shared')
    result = assets.get_collection_asset_root_preview(session, **arguments)
    assert result.path is None
    assert 'another collection' in result.reason
