from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.db.models.CollectionLocalAsset import CollectionLocalAsset
from backend.utils.collection_asset_files import ArtworkConflict, PreparedCollectionAsset, asset_file_hash
from task_manager.tasks.workers.reconcile_collection_assets import service


@pytest.fixture
def writer(tmp_path, monkeypatch):
    metadata = sa.MetaData()
    collections = sa.Table("collections", metadata, sa.Column("id", sa.Integer, primary_key=True))
    profiles = sa.Table("local_media_profiles", metadata, sa.Column("id", sa.Integer, primary_key=True))
    CollectionLocalAsset.__table__.to_metadata(metadata)
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(collections.insert(), [{"id": 1}, {"id": 2}])
        connection.execute(profiles.insert(), [{"id": 1}, {"id": 2}])

    state = SimpleNamespace(
        active_sessions=0,
        requests=0,
        media_paths=[],
        image=b"prepared image bytes",
        current_root=tmp_path / "collection",
        source_format="jpg",
        fallback_format="jpg",
    )

    class WorkerSession:
        def __init__(self, session):
            self.session = session

        def __getattr__(self, name):
            return getattr(self.session, name)

        def get(self, model, key):
            if model is service.Collection:
                return SimpleNamespace(id=key)
            if model is service.CollectionLocalMediaProfile:
                return SimpleNamespace(
                    id=key, output_template="template", filename_restriction_mode="windows",
                    download_collection_assets=True, show_nfo=False,
                )
            return self.session.get(model, key)

        def scalars(self, statement):
            # Only the media-download path lookup is faked; artwork rows also
            # select file_path and must come from the real table.
            columns = list(statement.selected_columns)
            if (
                [column.key for column in columns] == ["file_path"]
                and columns[0].table is not CollectionLocalAsset.__table__
            ):
                return state.media_paths
            return self.session.scalars(statement)

    @contextmanager
    def session_scope():
        state.active_sessions += 1
        session = Session(engine)
        try:
            yield WorkerSession(session)
        finally:
            session.close()
            state.active_sessions -= 1

    def download(
        _url,
        workspace,
        *,
        ffmpeg_path,
        fallback_format,
        forced_format=None,
        check_canceled,
    ):
        assert state.active_sessions == 0, "HTTP must not pin a database transaction"
        check_canceled()
        state.requests += 1
        fallback = str(getattr(fallback_format, "value", fallback_format))
        output_format = forced_format or (
            state.source_format if state.source_format in {"jpg", "png"} else fallback
        )
        path = workspace / f"asset.{output_format}"
        path.write_bytes(state.image)
        return PreparedCollectionAsset(path, state.source_format, output_format)

    def write_transaction(work, *, concurrent=False):
        with session_scope() as session:
            result = work(session)
            session.commit()
            return result

    monkeypatch.setattr(service, "db_session", session_scope)
    monkeypatch.setattr(service, "run_write_transaction", write_transaction)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(download_settings=SimpleNamespace(
            ffmpeg_path="ffmpeg",
            collection_artwork_fallback_format=state.fallback_format,
        )),
    )
    monkeypatch.setattr(service, "_current", lambda *_: True)
    monkeypatch.setattr(service, "collection_profile_roots", lambda *_: {})
    monkeypatch.setattr(service, "collection_profile_is_managed", lambda *_: True)
    monkeypatch.setattr(service, "collection_assets_enabled", lambda _: True)
    monkeypatch.setattr(service, "resolve_collection_media_directory", lambda *_, **__: SimpleNamespace(path=str(state.current_root)))
    monkeypatch.setattr(service, "download_collection_asset", download)
    plan = service.AssetPlan(
        1,
        1,
        "poster",
        "https://example.invalid/poster",
        state.current_root,
        tmp_path,
        "template",
    )
    state.engine, state.plan = engine, plan
    yield state
    engine.dispose()


def _active():
    pass


def _target(writer, extension=None, kind="poster"):
    if extension is None:
        extension = (
            writer.source_format
            if writer.source_format in {"jpg", "png"}
            else writer.fallback_format
        )
    return writer.current_root / f"{kind}.{extension}"


def _rows(writer):
    with Session(writer.engine) as session:
        return list(session.scalars(sa.select(CollectionLocalAsset)))


def test_download_ownership_is_durable_and_refresh_is_idempotent(writer):
    assert service._refresh_asset(writer.plan, _active)
    rows = _rows(writer)
    target = _target(writer)
    assert len(rows) == 1
    assert rows[0].content_hash == asset_file_hash(target)
    assert rows[0].source_format == "jpg"
    assert rows[0].pending_hash is None
    assert rows[0].source_url == writer.plan.url
    assert service._refresh_asset(writer.plan, _active)
    assert writer.requests == 1


def test_native_png_is_published_as_png(writer):
    writer.source_format = "png"
    service._refresh_asset(writer.plan, _active)
    assert _target(writer).exists()
    assert not _target(writer, "jpg").exists()
    assert _rows(writer)[0].source_format == "png"


def test_profiles_sharing_one_collection_directory_share_artwork_without_redownloading(writer):
    service._refresh_asset(writer.plan, _active)
    service._refresh_asset(replace(writer.plan, profile_id=2), _active)
    rows = _rows(writer)
    assert {row.local_media_profile_id for row in rows} == {1, 2}
    assert len({row.content_hash for row in rows}) == 1
    assert writer.requests == 1


def test_other_collections_cannot_claim_existing_artwork(writer):
    service._refresh_asset(writer.plan, _active)
    with pytest.raises(ArtworkConflict, match="Another collection"):
        service._refresh_asset(replace(writer.plan, collection_id=2), _active)
    assert writer.requests == 2


def test_preexisting_custom_artwork_is_never_adopted(writer):
    target = _target(writer)
    target.parent.mkdir()
    target.write_bytes(b"custom poster")
    with pytest.raises(ArtworkConflict, match="User-supplied"):
        service._refresh_asset(writer.plan, _active)
    assert writer.requests == 1
    assert not _rows(writer)


def test_external_modification_is_preserved(writer):
    service._refresh_asset(writer.plan, _active)
    target = _target(writer)
    target.write_bytes(b"edited poster")
    with pytest.raises(ArtworkConflict, match="edited"):
        service._refresh_asset(writer.plan, _active)
    assert target.read_bytes() == b"edited poster"


def test_custom_alternate_format_is_preserved(writer):
    service._refresh_asset(writer.plan, _active)
    target = _target(writer)
    alternate = target.with_suffix(".png")
    alternate.write_bytes(b"custom png")
    writer.image = b"updated image"
    with pytest.raises(ArtworkConflict, match="alternate-format"):
        service._refresh_asset(
            replace(writer.plan, url="https://example.invalid/new-poster"),
            _active,
        )
    assert target.exists()
    assert alternate.read_bytes() == b"custom png"


def test_upstream_url_change_refreshes_owned_file(writer):
    service._refresh_asset(writer.plan, _active)
    writer.image = b"updated jpeg bytes"
    updated = replace(writer.plan, url="https://example.invalid/new-poster")
    service._refresh_asset(updated, _active)
    assert _target(writer).read_bytes() == writer.image
    assert _rows(writer)[0].source_url == updated.url
    assert writer.requests == 2


def test_upstream_format_change_replaces_managed_variant(writer):
    service._refresh_asset(writer.plan, _active)
    old = _target(writer, "jpg")
    writer.source_format = "png"
    writer.image = b"prepared png bytes"
    updated = replace(writer.plan, url="https://example.invalid/new-poster")
    service._refresh_asset(updated, _active)
    new = _target(writer, "png")
    assert new.read_bytes() == writer.image
    assert not old.exists()
    assert {row.file_path for row in _rows(writer)} == {str(new)}


def test_fallback_change_reprocesses_non_native_asset(writer):
    writer.source_format = "other"
    service._refresh_asset(writer.plan, _active)
    old = _target(writer, "jpg")
    writer.fallback_format = "png"
    service._refresh_asset(writer.plan, _active)
    new = _target(writer, "png")
    assert writer.requests == 2
    assert new.exists()
    assert not old.exists()
    assert _rows(writer)[0].source_format == "other"


def test_forced_clearlogo_is_always_png(writer):
    writer.source_format = "other"
    logo_plan = replace(
        writer.plan,
        kind="clearlogo",
        url="https://example.invalid/logo",
        forced_format="png",
    )
    service._refresh_asset(logo_plan, _active)
    assert _target(writer, "png", "clearlogo").exists()


def test_expired_same_url_is_checked_again(writer, monkeypatch):
    service._refresh_asset(writer.plan, _active)
    monkeypatch.setattr(service, "_REFRESH_AFTER", timedelta(seconds=-1))
    writer.image = b"changed in place"
    service._refresh_asset(writer.plan, _active)
    assert writer.requests == 2
    assert _target(writer).read_bytes() == writer.image


def test_failure_after_atomic_replace_is_recoverable_from_pending_hash(writer, monkeypatch):
    publish = service.publish_collection_asset

    def interrupted(*args, **kwargs):
        publish(*args, **kwargs)
        raise RuntimeError("process interrupted after publication")

    monkeypatch.setattr(service, "publish_collection_asset", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        service._refresh_asset(writer.plan, _active)
    target = _target(writer)
    row = _rows(writer)[0]
    assert row.pending_hash == asset_file_hash(target)
    assert row.content_hash is None
    monkeypatch.setattr(service, "publish_collection_asset", publish)
    service._refresh_asset(writer.plan, _active)
    row = _rows(writer)[0]
    assert row.content_hash == asset_file_hash(target)
    assert row.pending_hash is None


def test_stale_profile_after_download_does_not_publish(writer, monkeypatch):
    answers = iter((True, False))
    monkeypatch.setattr(service, "_current", lambda *_: next(answers))
    assert service._refresh_asset(writer.plan, _active) is False
    assert not _target(writer).exists()
    assert not _rows(writer)


def test_network_failure_keeps_previous_artwork(writer, monkeypatch):
    service._refresh_asset(writer.plan, _active)
    target = _target(writer)
    original = target.read_bytes()

    def fail(*args, **kwargs):
        assert writer.active_sessions == 0
        raise OSError("network unavailable")

    monkeypatch.setattr(service, "download_collection_asset", fail)
    with pytest.raises(OSError):
        service._refresh_asset(replace(writer.plan, url="https://example.invalid/new"), _active)
    assert target.read_bytes() == original
    assert _rows(writer)[0].pending_hash is None


def test_old_root_waits_for_media_rename_and_valid_replacement(writer):
    service._refresh_asset(writer.plan, _active)
    old = _target(writer)
    writer.current_root = old.parent.parent / "renamed collection"
    new_plan = replace(writer.plan, directory=writer.current_root)
    service._cleanup_old_roots(1, 1, writer.current_root, writer.plan.download_root, _active)
    assert old.exists()
    service._refresh_asset(new_plan, _active)
    writer.media_paths = [str(old.parent / "possibly externally renamed.mp4")]
    service._cleanup_old_roots(1, 1, writer.current_root, writer.plan.download_root, _active)
    assert old.exists()
    writer.media_paths = [str(writer.current_root / "episode.mp4")]
    service._cleanup_old_roots(1, 1, writer.current_root, writer.plan.download_root, _active)
    assert not old.exists()
    assert _target(writer).exists()
    assert len(_rows(writer)) == 1


def test_relocation_preserves_artwork_still_owned_by_another_profile(writer):
    service._refresh_asset(writer.plan, _active)
    service._refresh_asset(replace(writer.plan, profile_id=2), _active)
    old = _target(writer)
    writer.current_root = old.parent.parent / "renamed collection"
    service._refresh_asset(replace(writer.plan, directory=writer.current_root), _active)
    service._cleanup_old_roots(1, 1, writer.current_root, writer.plan.download_root, _active)
    assert old.exists()
    assert {(row.local_media_profile_id, row.file_path) for row in _rows(writer)} == {
        (1, str(_target(writer))), (2, str(old)),
    }


def _nfo_plan(writer, path=None, content=b"<tvshow><title>Show</title></tvshow>", kind="tvshow"):
    from backend.services.collection_assets import CollectionNfoFile

    path = path or writer.current_root / "tvshow.nfo"
    return service.NfoPlan(1, 1, writer.current_root, writer.plan.download_root, CollectionNfoFile(kind, path, content))


@pytest.fixture
def nfo_writer(writer, monkeypatch):
    monkeypatch.setattr(service, "_current_nfo", lambda *_: True)
    writer.emptied = []
    monkeypatch.setattr(service, "remove_folders_left_empty", lambda folders, **_: writer.emptied.extend(folders))
    return writer


def test_show_nfo_is_written_once_and_rewritten_when_it_changes(nfo_writer):
    plan = _nfo_plan(nfo_writer)
    assert service._write_nfo(plan, _active)
    target = plan.file.path
    assert target.read_bytes() == plan.file.content
    [row] = _rows(nfo_writer)
    assert (row.asset_type, row.content_hash, row.pending_hash) == ("tvshow", asset_file_hash(target), None)

    assert service._write_nfo(plan, _active)
    changed = _nfo_plan(nfo_writer, content=b"<tvshow><title>Renamed</title></tvshow>")
    assert service._write_nfo(changed, _active)
    assert target.read_bytes() == changed.file.content
    assert [row.content_hash for row in _rows(nfo_writer)] == [asset_file_hash(target)]


def test_a_show_nfo_someone_else_wrote_is_left_alone(nfo_writer):
    plan = _nfo_plan(nfo_writer)
    plan.file.path.parent.mkdir()
    plan.file.path.write_bytes(b"<tvshow><title>Mine</title></tvshow>")
    with pytest.raises(ArtworkConflict):
        service._write_nfo(plan, _active)
    assert plan.file.path.read_bytes() == b"<tvshow><title>Mine</title></tvshow>"
    assert not _rows(nfo_writer)


def test_a_season_nfo_that_is_no_longer_wanted_is_removed_with_its_folder(nfo_writer):
    old = _nfo_plan(nfo_writer, nfo_writer.current_root / "Season 1" / "season.nfo", b"<season/>", "season-1")
    service._write_nfo(old, _active)
    edited = _nfo_plan(nfo_writer, nfo_writer.current_root / "Season 2" / "season.nfo", b"<season/>", "season-2")
    service._write_nfo(edited, _active)
    edited.file.path.write_bytes(b"<season><title>My own</title></season>")

    service._cleanup_unwanted_nfos(1, 1, set(), nfo_writer.plan.download_root, _active)

    assert not old.file.path.exists()
    assert nfo_writer.emptied == [old.file.path.parent]
    # A file changed since VODLoft wrote it stays; VODLoft only stops keeping it.
    assert edited.file.path.exists()
    assert not _rows(nfo_writer)
