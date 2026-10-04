"""End-to-end checks for the generic library without upstream network access."""

import importlib
import sys
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import create_app
from backend.db.core import Base, load_database_models
from backend.db.models.vodloft import Artifact, CollectionEntry, MediaItem
from config import get_settings
from source_contracts import DownloadResult, EntrySnapshot, MediaSnapshot, SourceMediaReference


def ref(namespace, upstream_id, url):
    return SourceMediaReference(source_id="fixture", domain="example.com", namespace=namespace,
                                upstream_id=upstream_id, url=url)


def test_shared_media_partial_scan_download_and_playback(monkeypatch, tmp_path):
    router = importlib.import_module("backend.api.endpoints.vodloft.router")
    feeds = importlib.import_module("backend.api.endpoints.vodloft.feeds")
    profiles = importlib.import_module("backend.api.endpoints.vodloft.profiles")
    finalization = importlib.import_module("backend.services.vodloft_finalization")
    gateway = importlib.import_module("backend.source_manager.gateway")
    load_database_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, autoflush=False)
    monkeypatch.setattr(router, "get_session", session_factory)
    monkeypatch.setattr(feeds, "get_session", session_factory)
    monkeypatch.setattr(profiles, "get_session", session_factory)
    monkeypatch.setattr(finalization, "get_session", session_factory)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)

    shared = ref("video", "same-video", "https://example.com/watch/same-video")
    snapshots = {
        f"https://example.com/list/{i}": MediaSnapshot(
            kind="collection", reference=ref("list", str(i), f"https://example.com/list/{i}"),
            title=f"List {i}", entries=[EntrySnapshot(reference=shared, title="Shared video", position=1)],
        ) for i in (1, 2)
    }

    def resolve(self, source_id, url, max_entries=100):
        return snapshots[url]

    def download(self, source_id, url, staging, preferred_format="format_1080p", **kwargs):
        path = Path(staging) / "media.mp4"
        path.write_bytes(b"prototype-media")
        return DownloadResult(filename=path.name, size=path.stat().st_size)

    monkeypatch.setattr(gateway.SourceGateway, "resolve", resolve)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    # HTTP checks omit the inherited scheduler lifespan, which has separate tests.
    client = TestClient(create_app())
    for i in (1, 2):
        response = client.post("/api/vodloft/import", json={"snapshot": snapshots[f"https://example.com/list/{i}"].model_dump()})
        assert response.status_code == 200, response.text
    with session_factory() as session:
        assert len(session.scalars(select(MediaItem)).all()) == 3
        assert len(session.scalars(select(CollectionEntry)).all()) == 2
        video_id = session.scalar(select(MediaItem).where(MediaItem.kind == "video")).id
    profile = client.post("/api/vodloft/profiles", json={"name": "Example video",
        "domain": "example.com", "preferred_format": "format_1080p",
        "output_template": "/downloads/{{ domain }}/{{ title }} - {{ id }}.ext"})
    assert profile.status_code == 201, profile.text

    # A later incomplete enumeration must not remove previously known entries.
    snapshots["https://example.com/list/1"] = snapshots["https://example.com/list/1"].model_copy(
        update={"entries": [], "enumeration_complete": False})
    response = client.post("/api/vodloft/import", json={"snapshot": snapshots["https://example.com/list/1"].model_dump()})
    assert response.status_code == 200, response.text
    with session_factory() as session:
        assert len(session.scalars(select(CollectionEntry)).all()) == 2

    response = client.post(f"/api/vodloft/library/{video_id}/download",
                           json={"profile_id": profile.json()["id"]})
    assert response.status_code == 200, response.text
    status = client.get(f"/api/vodloft/jobs/{response.json()['id']}")
    assert status.json()["state"] == "available"
    playback = client.get(f"/api/vodloft/library/{video_id}/play")
    assert playback.status_code == 200
    assert playback.content == b"prototype-media"
    ranged = client.get(f"/api/vodloft/library/{video_id}/play", headers={"Range": "bytes=0-4"})
    assert ranged.status_code == 206 and ranged.content == b"proto"

    collection_id = client.get("/api/vodloft/library").json()[0]["id"]
    subscription = client.post(f"/api/vodloft/library/{collection_id}/feed")
    assert subscription.status_code == 200, subscription.text
    feed_url = subscription.json()["url"]
    feed = client.get(feed_url)
    assert feed.status_code == 200
    root = ElementTree.fromstring(feed.content)
    enclosure_url = root.find("channel/item/enclosure").attrib["url"]
    assert client.get(enclosure_url).content == b"prototype-media"
    enclosure_range = client.get(enclosure_url, headers={"Range": "bytes=0-4"})
    assert enclosure_range.status_code == 206 and enclosure_range.content == b"proto"
    with session_factory() as session:
        artifact_path = session.scalar(select(Artifact).where(Artifact.item_id == video_id)).path
    Path(artifact_path).write_bytes(b"changed-artifact")
    assert client.get(enclosure_url).content == b"prototype-media"
    assert client.delete(f"/api/vodloft/library/{collection_id}/feed").status_code == 200
    assert client.get(feed_url).status_code == 404
    assert not list((tmp_path / "vodloft-feeds").rglob(f"{video_id}.mp4"))
    filtered = client.post(f"/api/vodloft/library/{collection_id}/stream-profiles", json={
        "name": "Filtered", "format": "video", "title_contains": "unrelated"})
    assert filtered.status_code == 201, filtered.text
    filtered_url = client.post(f"/api/vodloft/stream-profiles/{filtered.json()['id']}/feed").json()["url"]
    assert ElementTree.fromstring(client.get(filtered_url).content).find("channel/item") is None
    assert client.post(f"/api/vodloft/library/{collection_id}/stream-profiles", json={
        "name": "Bad date", "published_after": "2026-12-01",
        "published_before": "2026-01-01"}).status_code == 422
    assert client.delete(f"/api/vodloft/library/{collection_id}").status_code == 204
    assert client.get(f"/api/vodloft/library/{video_id}/play").content == b"changed-artifact"
    with session_factory() as session:
        assert len(session.scalars(select(CollectionEntry)).all()) == 1
        assert Path(artifact_path).is_file()


def test_public_url_rejects_local_targets(monkeypatch):
    gateway = importlib.import_module("backend.source_manager.gateway")
    import pytest
    with pytest.raises(ValueError):
        gateway.validate_public_url("http://127.0.0.1/private")
    with pytest.raises(ValueError):
        gateway.validate_public_url("file:///etc/passwd")


def test_third_source_uses_the_generic_process_contract(tmp_path, monkeypatch):
    gateway_module = importlib.import_module("backend.source_manager.gateway")
    worker = tmp_path / "fixture_source.py"
    worker.write_text(
        "import json,sys\n"
        "request=json.load(sys.stdin)\n"
        "print(json.dumps({'source_id':'fixture','display_name':'Fixture',"
        "'version':'1','capabilities':['resolve_url']}))\n"
    )
    gateway = gateway_module.SourceGateway({"fixture": [sys.executable, str(worker)]})
    assert [manifest.source_id for manifest in gateway.manifests()] == ["fixture"]


def test_source_error_envelope_stays_typed_and_redacted(tmp_path):
    import pytest
    gateway_module = importlib.import_module("backend.source_manager.gateway")
    worker = tmp_path / "error_source.py"
    worker.write_text("import json,sys\njson.load(sys.stdin)\n"
        "print(json.dumps({'error': {'code': 'authentication_required',"
        "'message': 'Authorization is required; token=secret-value'}}))\n")
    gateway = gateway_module.SourceGateway({"fixture": [sys.executable, str(worker)]})
    with pytest.raises(gateway_module.SourceInvocationError) as error:
        gateway.call("fixture", "resolve")
    assert error.value.code == "authentication_required"
    assert "Authorization is required" == str(error.value)
    assert "secret-value" not in str(error.value)
