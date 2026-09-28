"""Policy and boundary checks using contract-compatible fixture Sources."""

import importlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import create_app
from backend.db.core import Base, load_database_models
from backend.db.models.vodloft import AcquisitionJob, Artifact, CollectionEntry, MediaItem, SourceReference
from config import get_settings
from source_contracts import DownloadResult, EntrySnapshot, MediaSnapshot, SourceManifest, SourceMediaReference


def ref(domain, upstream_id):
    return SourceMediaReference(source_id="fixture", domain=domain, namespace="video",
        upstream_id=upstream_id, url=f"https://{domain}/watch/{upstream_id}")


@pytest.fixture
def library(monkeypatch, tmp_path):
    router = importlib.import_module("backend.api.endpoints.vodloft.router")
    profiles = importlib.import_module("backend.api.endpoints.vodloft.profiles")
    automation = importlib.import_module("backend.api.endpoints.vodloft.automation")
    feeds = importlib.import_module("backend.api.endpoints.vodloft.feeds")
    connections = importlib.import_module("backend.api.endpoints.vodloft.connections")
    integrations = importlib.import_module("backend.api.endpoints.vodloft.integrations")
    finalization = importlib.import_module("backend.services.vodloft_finalization")
    gateway = importlib.import_module("backend.source_manager.gateway")
    load_database_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, autoflush=False)
    for module in (router, profiles, automation, feeds, connections, integrations, finalization):
        monkeypatch.setattr(module, "get_session", sessions)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    monkeypatch.setenv("VODLOFT_SOURCE_RUNTIME_ROOT", str(tmp_path / "runtimes"))
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1", capabilities={"resolve_url", "download"})])
    return TestClient(create_app()), sessions, router, gateway, automation


def test_collection_policy_matches_member_domain_and_feed_representation(library, monkeypatch, tmp_path):
    client, sessions, router, gateway, automation = library
    first, second = ref("example.com", "first"), ref("other.example", "second")
    collection = MediaSnapshot(kind="collection", reference=SourceMediaReference(
        source_id="fixture", domain="example.com", namespace="list", upstream_id="l1",
        url="https://example.com/list/l1"), title="Mixed collection",
        entries=[EntrySnapshot(reference=first, title="First", position=1),
                 EntrySnapshot(reference=second, title="Second", position=2)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    imported = client.post("/api/vodloft/import", json={"snapshot": collection.model_dump()})
    assert imported.status_code == 200, imported.text
    collection_id = imported.json()["id"]
    profile_ids = []
    for fmt in ("format_audio_only", "format_1080p"):
        response = client.post("/api/vodloft/profiles", json={"name": fmt, "domain": "example.com",
            "preferred_format": fmt,
            "output_template": f"/downloads/example.com/{fmt}/" + "{{ title }} - {{ id }}.ext"})
        assert response.status_code == 201, response.text
        profile_ids.append(response.json()["id"])
    policy = client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={
        "name": "Mixed", "local_profile_ids": profile_ids, "backfill": "all"})
    assert policy.status_code == 201, policy.text
    queued = automation.schedule_profile(policy.json()["id"], dispatch=False)
    assert len(queued["queued_job_ids"]) == 2
    assert len(queued["skipped"]) == 1
    assert queued["skipped"][0]["reason"].endswith("item's Domain")
    assert automation.schedule_profile(policy.json()["id"], dispatch=False)["queued_job_ids"] == []

    def download(self, source_id, url, staging, preferred_format="format_1080p", **kw):
        ext = ".mp3" if preferred_format == "format_audio_only" else ".mp4"
        output = Path(staging) / f"media{ext}"
        output.write_bytes(preferred_format.encode())
        return DownloadResult(filename=output.name, size=output.stat().st_size)

    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    for job_id in queued["queued_job_ids"]:
        router._run_download(job_id)
    with sessions() as session:
        first_item = session.scalar(select(MediaItem).where(MediaItem.title == "First"))
        assert len(session.scalars(select(Artifact).where(Artifact.item_id == first_item.id)).all()) == 2
        jobs = session.scalars(select(AcquisitionJob)).all()
        assert {j.execution_spec["runtime_version"] for j in jobs} == {"configured"}
        assert all(j.state == "available" and j.active_key is None for j in jobs)

    audio = client.post(f"/api/vodloft/library/{collection_id}/stream-profiles",
        json={"name": "Audio", "format": "audio"})
    video = client.post(f"/api/vodloft/library/{collection_id}/stream-profiles",
        json={"name": "Video", "format": "video"})
    assert audio.status_code == video.status_code == 201
    for profile, extension in ((audio, ".mp3"), (video, ".mp4")):
        url = client.post(f"/api/vodloft/stream-profiles/{profile.json()['id']}/feed").json()["url"]
        feed = ElementTree.fromstring(client.get(url).content)
        enclosure = feed.find("channel/item/enclosure")
        assert enclosure.attrib["url"].endswith(extension)
        assert client.get(enclosure.attrib["url"]).status_code == 200


def test_source_account_references_share_media_without_leaking_secrets(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "shared"), title="Shared")
    seen = []
    def resolve(self, source_id, url, **kwargs):
        seen.append(kwargs.get("access_token"))
        return snapshot
    monkeypatch.setattr(gateway.SourceGateway, "resolve", resolve)
    accounts = []
    for name in ("Alice", "Bob"):
        response = client.post("/api/vodloft/sources/connections", json={
            "source_id": "fixture", "name": name, "access_token": f"secret-{name}"})
        assert response.status_code == 201, response.text
        assert "secret-" not in response.text
        accounts.append(response.json()["id"])
        imported = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(),
            "connection_id": accounts[-1]})
        assert imported.status_code == 200, imported.text
    assert seen == ["secret-Alice", "secret-Bob"]
    with sessions() as session:
        assert len(session.scalars(select(MediaItem)).all()) == 1
        refs = session.scalars(select(SourceReference)).all()
        assert {r.connection_id for r in refs} == set(accounts)
        assert len({r.item_id for r in refs}) == 1
    assert "secret-" not in client.get("/api/vodloft/sources/connections").text
    item_id = imported.json()["id"]
    edited = client.put(f"/api/vodloft/library/{item_id}/metadata", json={
        "title": "My title", "description": "My notes"})
    assert edited.status_code == 200
    snapshot.title = "Changed upstream title"
    client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(),
        "connection_id": accounts[-1]})
    item = client.get(f"/api/vodloft/library/{item_id}").json()
    assert item["title"] == "My title" and item["description"] == "My notes"


def test_bad_source_bundle_digest_never_activates(monkeypatch, tmp_path):
    from backend.source_manager import runtime
    monkeypatch.setenv("VODLOFT_SOURCE_RUNTIME_ROOT", str(tmp_path / "runtimes"))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bad.whl").write_bytes(b"bad")
    (bundle / "release.json").write_text(json.dumps({"source_id": "yt-dlp", "version": "0.1.0",
        "wheels": {"bad.whl": "0" * 64}}))
    with pytest.raises(ValueError, match="digest"):
        runtime.install_bundle("yt-dlp", bundle)
    assert runtime.status()["active"] == {}


def test_builtin_source_connect_guard_rejects_redirect_to_private_ip():
    import socket
    from source_contracts.network import install_public_network_guard
    original_lookup = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    try:
        socket.getaddrinfo = lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port))]
        install_public_network_guard()
        from types import SimpleNamespace
        fake_socket = SimpleNamespace(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0)
        with pytest.raises(OSError, match="private or local"):
            socket.socket.connect(fake_socket, ("public.example", 80))
    finally:
        socket.getaddrinfo = original_lookup
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


def test_finalization_recovery_restores_previous_presentation(library, monkeypatch, tmp_path):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "v1"), title="Versioned")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Versioned",
        "domain": "example.com", "output_template": "/downloads/presented/{{ title }}.ext"}).json()["id"]

    def download(self, source_id, url, staging, **kwargs):
        path = Path(staging) / "media.mp4"
        path.write_bytes(b"original")
        return DownloadResult(filename=path.name, size=path.stat().st_size)

    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    assert client.post(f"/api/vodloft/library/{item_id}/download",
        json={"profile_id": profile_id}).status_code == 200
    from backend.db.models.vodloft import ArtifactPlacement, FileFinalization
    from backend.services import vodloft_finalization
    with sessions() as session:
        reference_id = session.scalar(select(SourceReference).where(SourceReference.item_id == item_id)).id
        old_placement = session.scalar(select(ArtifactPlacement))
        output = Path(old_placement.path)
        job = AcquisitionJob(item_id=item_id, reference_id=reference_id, profile_id=profile_id,
            state="finalizing", active_key=f"{item_id}:{profile_id}")
        session.add(job)
        session.commit()
        job_id = job.id
    destination = tmp_path / "vodloft" / f"{item_id}-{job_id}.mp4"
    vodloft_finalization.prepare(job_id, destination, output)
    destination.write_bytes(b"incomplete replacement")
    output.write_bytes(b"incomplete replacement")
    vodloft_finalization.advance(job_id, "content")
    vodloft_finalization.reconcile(job_id)
    assert output.read_bytes() == b"original"
    assert not destination.exists()
    with sessions() as session:
        assert session.scalar(select(FileFinalization)) is None


def test_cancel_queued_job_releases_active_identity(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "cancel"), title="Cancel")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Cancel",
        "domain": "example.com", "output_template": "/downloads/cancel/{{ title }}.ext"}).json()["id"]
    job_id, state, created = router.queue_download(item_id, profile_id)
    assert state == "queued" and created
    assert client.post(f"/api/vodloft/jobs/{job_id}/cancel").status_code == 200
    router._run_download(job_id)
    with sessions() as session:
        job = session.get(AcquisitionJob, job_id)
        assert job.state == "canceled" and job.active_key is None


def test_cancel_running_source_terminates_process(tmp_path):
    import threading
    import time
    from backend.source_manager import gateway as gateway_module
    worker = tmp_path / "worker.py"
    worker.write_text("import json,sys,time\njson.load(sys.stdin)\ntime.sleep(30)\n")
    gateway = gateway_module.SourceGateway({"fixture": [sys.executable, str(worker)]})
    errors = []
    thread = threading.Thread(target=lambda: _call(errors, gateway))
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with gateway_module._running_lock:
            if 42 in gateway_module._running:
                break
        time.sleep(0.01)
    gateway_module.cancel_running_job(42)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors and isinstance(errors[0], RuntimeError)


def _call(errors, gateway):
    try:
        gateway.call("fixture", "download", job_id=42)
    except Exception as exc:
        errors.append(exc)
