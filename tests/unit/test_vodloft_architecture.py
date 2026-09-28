"""Policy and boundary checks using contract-compatible fixture Sources."""

import importlib
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import create_app
from backend.db.core import Base, load_database_models
from backend.db.models.vodloft import AcquisitionJob, Artifact, CollectionEntry, CollectionScan, MediaItem, SourceReference
from config import get_settings
from source_contracts import CollectionPage, DownloadResult, EntrySnapshot, MediaSnapshot, SourceManifest, SourceMediaReference


def test_source_contract_and_generic_gateway_keep_package_boundary():
    root = Path(__file__).resolve().parents[2] / "server"
    files = [*(root / "source_contracts" / "src" / "source_contracts").rglob("*.py"),
        root / "backend" / "src" / "backend" / "source_manager" / "gateway.py"]
    for path in files:
        tree = ast.parse(path.read_text())
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names]
        imports.extend(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))
        if "source_contracts" in path.parts:
            assert not any(name.startswith(("backend", "sqlalchemy", "config", "dailywire_api"))
                           for name in imports), path
        else:
            assert not any(name.startswith(("vodloft_source_", "dailywire_api", "yt_dlp"))
                           for name in imports), path


def test_media_server_item_matching_pages_and_scopes_library(monkeypatch):
    integrations = importlib.import_module("backend.api.endpoints.vodloft.integrations")
    requested = []
    target_path = "/media/collection/item.mp4"
    for kind in ("plex", "jellyfin", "audiobookshelf"):
        target = SimpleNamespace(kind=kind, library_id="library-1")
        def request(_target, method, path):
            requested.append(path)
            second_page = "Start=200" in path or "StartIndex=200" in path or "page=1" in path
            if kind == "plex":
                if not second_page:
                    return ("<MediaContainer totalSize='201'>" +
                        "<Video ratingKey='missing'><Media><Part file='/other' /></Media></Video>" * 200 +
                        "</MediaContainer>").encode()
                return ("<MediaContainer totalSize='201'><Video ratingKey='plex-7'><Media>"
                    f"<Part file='{target_path}' /></Media></Video></MediaContainer>").encode()
            if kind == "jellyfin":
                return json.dumps({"TotalRecordCount": 201, "Items":
                    ([{"Id": str(i), "Path": "/other"} for i in range(200)] if not second_page else
                     [{"Id": "jellyfin-7", "Path": target_path}])}).encode()
            return json.dumps({"total": 201, "results":
                ([{"id": str(i), "path": "/other"} for i in range(200)] if not second_page else
                 [{"id": "abs-7", "media": {"audioFiles": [{"metadata": {"path": target_path}}]}}])}).encode()
        monkeypatch.setattr(integrations, "_request", request)
        assert integrations._find_remote(target, target_path) == {
            "plex": "plex-7", "jellyfin": "jellyfin-7", "audiobookshelf": "abs-7"}[kind]
        assert len(requested) == 2
        if kind == "jellyfin":
            assert all("ParentId=library-1" in path for path in requested)
        requested.clear()


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
        source_id="fixture", display_name="Fixture", version="1", capabilities={"resolve_url", "download"},
        configuration_schema=[{"name": "access_token", "label": "Access token", "kind": "secret"}])])
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
        from task_manager.scheduler.db import TaskOperation
        assert all(session.get(TaskOperation, j.operation_id).status == "SUCCEEDED" for j in jobs)

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
            "source_id": "fixture", "name": name, "secrets": {"access_token": f"secret-{name}"}})
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
    assert {r["connection_id"] for r in item["references"]} == set(accounts)
    local = client.post("/api/vodloft/profiles", json={"name": "Shared", "domain": "example.com",
        "output_template": "/downloads/shared/{{ title }}.ext"}).json()["id"]
    assert client.post(f"/api/vodloft/library/{item_id}/download", json={"profile_id": local}).status_code == 409
    selected = next(r["id"] for r in item["references"] if r["connection_id"] == accounts[1])
    job_id, state, created = router.queue_download(item_id, local, reference_id=selected)
    assert created and state == "queued"
    with sessions() as session:
        job = session.get(AcquisitionJob, job_id)
        assert job.reference_id == selected and job.execution_spec["connection_id"] == accounts[1]
    other = next(r["id"] for r in item["references"] if r["connection_id"] == accounts[0])
    assert client.post(f"/api/vodloft/library/{item_id}/download", json={
        "profile_id": local, "reference_id": other}).status_code == 409


def test_manifest_declared_connection_settings_are_scoped_and_secret(library, monkeypatch):
    client, sessions, _, gateway, _ = library
    connections_module = importlib.import_module("backend.api.endpoints.vodloft.connections")
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1", capabilities={"resolve_url"},
        configuration_schema=[
            {"name": "region", "label": "Region", "kind": "select", "options": ["eu", "us"], "required": True},
            {"name": "limit_per_day", "label": "Daily limit", "kind": "number"},
            {"name": "client_secret", "label": "Client secret", "kind": "secret", "required": True}])])
    endpoint = "/api/vodloft/sources/connections"
    invalid = client.post(endpoint, json={"source_id": "fixture", "name": "Bad",
        "settings": {"region": "wrong"}, "secrets": {"client_secret": "sensitive"}})
    assert invalid.status_code == 422
    response = client.post(endpoint, json={"source_id": "fixture", "name": "Configured",
        "settings": {"region": "eu", "limit_per_day": 10}, "secrets": {"client_secret": "sensitive"}})
    assert response.status_code == 201, response.text
    assert "sensitive" not in response.text and response.json()["secret_fields"] == ["client_secret"]
    with sessions() as session:
        assert connections_module.source_options(session, "fixture", response.json()["id"]) == {
            "region": "eu", "limit_per_day": 10, "client_secret": "sensitive"}
    received = []
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "settings"), title="Settings")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **options:
        (received.append(options), snapshot)[1])
    imported = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json"),
        "connection_id": response.json()["id"]})
    assert imported.status_code == 200 and received == [{
        "region": "eu", "limit_per_day": 10, "client_secret": "sensitive"}]


def test_source_authentication_error_is_distinct_from_app_login(library, monkeypatch):
    client, _, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "auth-needed"), title="Auth")
    def require_auth(*args, **kwargs):
        raise gateway.SourceInvocationError("authentication_required", "Authorization is required")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", require_auth)
    response = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")})
    assert response.status_code == 409
    assert response.headers["X-VodLoft-Source-Error"] == "authentication_required"
    assert response.json()["detail"] == "Authorization is required"


def test_collection_policy_pins_account_and_matches_child_reference(library, monkeypatch):
    client, sessions, router, gateway, automation = library
    child = ref("example.com", "account-video")
    collection = MediaSnapshot(kind="collection", reference=SourceMediaReference(
        source_id="fixture", domain="example.com", namespace="list", upstream_id="account-list",
        url="https://example.com/list/account-list"), title="Account list",
        entries=[EntrySnapshot(reference=child, title="Account video", position=1)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    imported = []
    for name in ("One", "Two"):
        account = client.post("/api/vodloft/sources/connections", json={
            "source_id": "fixture", "name": name, "secrets": {"access_token": f"secret-{name}"}}).json()["id"]
        imported.append(client.post("/api/vodloft/import", json={
            "snapshot": collection.model_dump(mode="json"), "connection_id": account}).json()["id"])
    collection_id = imported[0]
    assert imported[1] == collection_id
    references = client.get(f"/api/vodloft/library/{collection_id}").json()["references"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Account",
        "domain": "example.com", "output_template": "/downloads/accounts/{{ title }}.ext"}).json()["id"]
    request = {"name": "Pinned", "local_profile_ids": [profile_id], "backfill": "all"}
    assert client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json=request).status_code == 422
    selected = references[1]["id"]
    response = client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={
        **request, "source_reference_id": selected})
    assert response.status_code == 201, response.text
    assert response.json()["source_reference_id"] == selected
    queued = automation.schedule_profile(response.json()["id"], dispatch=False)
    assert len(queued["queued_job_ids"]) == 1
    with sessions() as session:
        parent = session.get(SourceReference, selected)
        job = session.get(AcquisitionJob, queued["queued_job_ids"][0])
        child_reference = session.get(SourceReference, job.reference_id)
        assert child_reference.connection_id == parent.connection_id
        assert child_reference.source_id == parent.source_id


def test_paged_collection_refresh_keeps_known_members_on_partial_failure(library, monkeypatch):
    client, sessions, router, gateway, _, = library
    collection = MediaSnapshot(kind="collection", reference=SourceMediaReference(
        source_id="fixture", domain="example.com", namespace="list", upstream_id="l1",
        url="https://example.com/list/l1"), title="List", entries=[EntrySnapshot(
            reference=ref("example.com", "old"), title="Old", position=1)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    collection_id = client.post("/api/vodloft/import", json={"snapshot": collection.model_dump(mode="json")}).json()["id"]
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1",
        capabilities={"resolve_url", "enumerate_pages"})])
    def page(self, source_id, url, *, cursor=None, **kwargs):
        if cursor:
            raise RuntimeError("Upstream page failed")
        return CollectionPage(entries=[EntrySnapshot(reference=ref("example.com", "new"),
            title="New", position=1)], next_cursor="opaque", complete=False)
    monkeypatch.setattr(gateway.SourceGateway, "entries", page)
    assert client.post(f"/api/vodloft/library/{collection_id}/refresh").status_code == 200
    with sessions() as session:
        assert {session.get(MediaItem, e.item_id).title for e in session.scalars(select(CollectionEntry)).all()} == {"Old", "New"}
        scan = session.scalar(select(CollectionScan).order_by(CollectionScan.id.desc()))
        assert not scan.complete and scan.error and scan.next_cursor == "opaque"

    resumed_cursors = []
    def final_page(self, source_id, url, *, cursor=None, **kwargs):
        resumed_cursors.append(cursor)
        return CollectionPage(entries=[EntrySnapshot(reference=ref("example.com", "new"),
            title="New", position=1)], complete=True)
    monkeypatch.setattr(gateway.SourceGateway, "entries", final_page)
    assert client.post(f"/api/vodloft/library/{collection_id}/refresh").status_code == 200
    assert resumed_cursors == ["opaque"]
    with sessions() as session:
        assert {session.get(MediaItem, e.item_id).title for e in session.scalars(select(CollectionEntry)).all()} == {"Old", "New"}
        assert session.scalar(select(CollectionScan).order_by(CollectionScan.id.desc())).complete


def test_playable_details_refresh_checks_identity_and_preserves_user_edits(library, monkeypatch):
    client, _, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "hydrated"), title="Unhydrated")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    assert client.put(f"/api/vodloft/library/{item_id}/metadata", json={
        "title": "Personal title", "description": "Personal notes"}).status_code == 200
    snapshot = snapshot.model_copy(update={"title": "Hydrated title", "description": "New upstream description"})
    result = client.post(f"/api/vodloft/library/{item_id}/refresh-details")
    assert result.status_code == 200, result.text
    item = client.get(f"/api/vodloft/library/{item_id}").json()
    assert item["title"] == "Personal title" and item["description"] == "Personal notes"
    snapshot = snapshot.model_copy(update={"reference": ref("example.com", "different")})
    assert client.post(f"/api/vodloft/library/{item_id}/refresh-details").status_code == 409


def test_source_snapshot_repair_restores_upstream_without_overwriting_user_title(library, monkeypatch):
    client, _, _, gateway, _ = library
    current = MediaSnapshot(kind="video", reference=ref("example.com", "repair"),
        title="First upstream title", description="First description")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: current)
    item_id = client.post("/api/vodloft/import", json={"snapshot": current.model_dump(mode="json")}).json()["id"]
    current = current.model_copy(update={"title": "Faulty upstream title", "description": "Bad description"})
    client.post("/api/vodloft/import", json={"snapshot": current.model_dump(mode="json")})
    edited = client.put(f"/api/vodloft/library/{item_id}/metadata", json={
        "title": "My title", "description": None})
    assert edited.status_code == 200
    history = client.get(f"/api/vodloft/library/{item_id}/source-history").json()
    assert len(history) == 2 and history[0]["metadata"]["title"] == "Faulty upstream title"
    assert "reference" not in history[0]["metadata"]
    response = client.post(f"/api/vodloft/library/{item_id}/source-history/{history[1]['id']}/restore")
    assert response.status_code == 200
    result = client.get(f"/api/vodloft/library/{item_id}").json()
    assert result["title"] == "My title" and result["description"] == "First description"


def test_explicitly_cleared_upstream_description_respects_user_override(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    url = "https://example.com/watch/clear"
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "clear"),
        title="Original", description="Upstream description")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "clear"), title="Original")
    client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()})
    with sessions() as session:
        assert session.get(MediaItem, item_id).description == "Upstream description"
    snapshot = snapshot.model_copy(update={"description": None})
    client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()})
    with sessions() as session:
        assert session.get(MediaItem, item_id).description is None


def test_stable_collection_occurrences_survive_reordering(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    shared = ref("example.com", "shared")
    collection_ref = SourceMediaReference(source_id="fixture", domain="example.com",
        namespace="list", upstream_id="duplicates", url="https://example.com/list/duplicates")
    snapshot = MediaSnapshot(kind="collection", reference=collection_ref, title="Duplicates",
        entries=[EntrySnapshot(reference=shared, title="Shared", position=1, occurrence_id="first"),
                 EntrySnapshot(reference=shared, title="Shared", position=2, occurrence_id="second")])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    collection_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    with sessions() as session:
        entries = session.scalars(select(CollectionEntry).where(CollectionEntry.collection_id == collection_id)).all()
        assert len(entries) == 2 and entries[0].item_id == entries[1].item_id
        original_ids = {entry.occurrence_key: entry.id for entry in entries}
    snapshot = snapshot.model_copy(update={"entries": [
        EntrySnapshot(reference=shared, title="Shared", position=1, occurrence_id="second"),
        EntrySnapshot(reference=shared, title="Shared", position=2, occurrence_id="first")]})
    client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()})
    with sessions() as session:
        entries = session.scalars(select(CollectionEntry).where(CollectionEntry.collection_id == collection_id)).all()
        assert {entry.occurrence_key: entry.id for entry in entries} == original_ids
        assert {entry.occurrence_key: entry.position for entry in entries} == {"first": 2, "second": 1}


def test_source_selection_prefers_specific_match_and_never_silently_falls_back(library, monkeypatch):
    client, _, router, gateway, _ = library
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [
        SourceManifest(source_id=source, display_name=source, version="1", capabilities={"resolve_url"})
        for source in ("specific", "generic")])
    monkeypatch.setattr(gateway, "validate_public_url", lambda url: url)
    monkeypatch.setattr(router, "validate_public_url", lambda url: url)
    from source_contracts import SourceMatch
    monkeypatch.setattr(gateway.SourceGateway, "match", lambda self, source_id, url: SourceMatch(
        source_id=source_id, confidence=100 if source_id == "specific" else 10))
    selected = []
    def resolve(self, source_id, url, **kwargs):
        selected.append(source_id)
        if source_id == "specific":
            raise RuntimeError("Account required")
        return MediaSnapshot(kind="video", reference=ref("example.com", "fallback"), title="Wrong")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", resolve)
    response = client.post("/api/vodloft/resolve", json={"url": "https://example.com/watch/1"})
    assert response.status_code == 502 and selected == ["specific"]
    response = client.post("/api/vodloft/resolve", json={
        "url": "https://example.com/watch/1", "source_id": "generic"})
    assert response.status_code == 200 and selected[-1] == "generic"


def test_operator_registered_third_source_appears_in_generic_endpoint(tmp_path, monkeypatch):
    registry = tmp_path / "trusted.json"
    registry.write_text(json.dumps({"sources": {"fixture": {
        "module": "fixture_source.worker", "package": "fixture-source"}}}))
    source = tmp_path / "fixture_source"
    source.mkdir()
    (source / "__init__.py").write_text("")
    (source / "worker.py").write_text(
        "import json,sys\n"
        "request=json.load(sys.stdin)\n"
        "print(json.dumps({'source_id':'fixture','display_name':'Fixture',"
        "'version':'1','capabilities':['resolve_url']}))\n")
    monkeypatch.setenv("VODLOFT_SOURCE_REGISTRY", str(registry))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + ":" + str(Path.cwd()))
    response = TestClient(create_app()).get("/api/vodloft/sources")
    assert response.status_code == 200
    assert "fixture" in {source["source_id"] for source in response.json()}


def test_local_playback_progress_survives_requests(library, monkeypatch):
    client, _, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "resume"), title="Resume")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    assert client.put(f"/api/vodloft/library/{item_id}/progress",
        json={"seconds": 125.5, "completed": False}).status_code == 200
    assert client.get(f"/api/vodloft/library/{item_id}/progress").json()["seconds"] == 125.5
    assert client.get("/api/vodloft/home").json()["continue"][0]["id"] == item_id
    client.put(f"/api/vodloft/library/{item_id}/progress",
        json={"seconds": 250, "completed": True})
    assert client.get("/api/vodloft/home").json()["continue"] == []


def test_job_lease_prevents_duplicate_execution(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "lease"), title="Lease")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    profile = client.post("/api/vodloft/profiles", json={"name": "Lease", "domain": "example.com",
        "output_template": "/downloads/lease/{{ title }}.ext"}).json()["id"]
    job_id, _, _ = router.queue_download(item_id, profile)
    owner = router._claim_job(job_id)
    assert owner and router._claim_job(job_id) is None
    router._run_download(job_id)
    with sessions() as session:
        assert session.get(AcquisitionJob, job_id).state == "queued"


def test_feed_token_is_redacted_from_access_log():
    import logging
    from backend.feed_logging import RedactFeedToken
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/feeds/vodloft/very-secret/media/1/audio.mp3", "1.1", 200), None)
    assert RedactFeedToken().filter(record)
    assert "very-secret" not in record.getMessage()


def test_collection_date_filter_skips_unknown_publication_dates(library, monkeypatch):
    from datetime import datetime, timezone
    client, sessions, _, gateway, automation = library
    collection = MediaSnapshot(kind="collection", reference=SourceMediaReference(
        source_id="fixture", domain="example.com", namespace="list", upstream_id="dated",
        url="https://example.com/list/dated"), title="Dated", entries=[
        EntrySnapshot(reference=ref("example.com", "in"), title="Include",
            position=1, published_at=datetime(2026, 9, 5, tzinfo=timezone.utc)),
        EntrySnapshot(reference=ref("example.com", "out"), title="Exclude",
            position=2, published_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        EntrySnapshot(reference=ref("example.com", "unknown"), title="Include unknown", position=3)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    collection_id = client.post("/api/vodloft/import", json={"snapshot": collection.model_dump(mode="json")}).json()["id"]
    local_profile = client.post("/api/vodloft/profiles", json={"name": "Dates", "domain": "example.com",
        "output_template": "/downloads/dates/{{ title }}.ext"}).json()["id"]
    policy = client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={
        "name": "September", "local_profile_ids": [local_profile], "backfill": "date_range",
        "published_after": "2026-09-01", "title_contains": "Include"})
    assert policy.status_code == 201, policy.text
    result = automation.schedule_profile(policy.json()["id"], dispatch=False)
    assert len(result["queued_job_ids"]) == 1
    assert len(result["skipped"]) == 2
    assert any(skip["reason"] == "Publication date is unknown" for skip in result["skipped"])


def test_typed_source_failure_records_stage_without_secret(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    from backend.source_manager.gateway import SourceInvocationError
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "auth"), title="Auth")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    profile = client.post("/api/vodloft/profiles", json={"name": "Auth", "domain": "example.com",
        "output_template": "/downloads/auth/{{ title }}.ext"}).json()["id"]
    def unavailable(self, source_id, url, staging, **kwargs):
        raise SourceInvocationError("authentication_required", "Source authorization is required")
    monkeypatch.setattr(gateway.SourceGateway, "download", unavailable)
    job_id, _, _ = router.queue_download(item_id, profile)
    router._run_download(job_id)
    status = client.get(f"/api/vodloft/jobs/{job_id}").json()
    assert status["state"] == "failed" and status["error_code"] == "authentication_required"
    assert status["failed_stage"] == "downloading" and "secret" not in str(status)


def test_running_job_keeps_queued_source_runtime_command(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "version"), title="Version")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump()}).json()["id"]
    profile = client.post("/api/vodloft/profiles", json={"name": "Version", "domain": "example.com",
        "output_template": "/downloads/version/{{ title }}.ext"}).json()["id"]
    active = ["old-runtime"]
    monkeypatch.setattr(gateway.SourceGateway, "__init__", lambda self, commands=None:
        setattr(self, "commands", commands if commands is not None else {"fixture": active.copy()}))
    job_id, _, _ = router.queue_download(item_id, profile)
    active[:] = ["new-runtime"]
    observed = []
    def download(self, source_id, url, staging, **kwargs):
        observed.append(self.commands[source_id])
        path = Path(staging) / "media.mp4"
        path.write_bytes(b"runtime-stable")
        return DownloadResult(filename=path.name, size=path.stat().st_size)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    router._run_download(job_id)
    assert observed == [["old-runtime"]]
    with sessions() as session:
        assert session.get(AcquisitionJob, job_id).state == "available"


def test_dailywire_pages_keep_season_group_and_opaque_cursor(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from dailywire_api.dw_api.client import EpisodesPaginatedResult
    from vodloft_source_dailywire import worker
    date = datetime(2026, 9, 5, tzinfo=timezone.utc)
    season = SimpleNamespace(dw_id="season-1", name="2026")
    show = SimpleNamespace(seasons=[season])
    calls = []
    class Client:
        def get_show_page(self, slug):
            return show
        def get_episodes_paginated(self, slug, selector):
            calls.append(selector)
            index = len(calls)
            record = SimpleNamespace(slug=f"ep-{index}", dw_id=f"id-{index}",
                sharing_url=f"https://www.dailywire.com/episode/ep-{index}",
                title=f"Episode {index}", published_date=date, episode_number=str(index))
            return EpisodesPaginatedResult([record],
                "https://middleware-prod.dailywire.com/middleware/v4/getPaginatedEpisodes?page=2"
                if index == 1 else None, index == 1)
    monkeypatch.setattr(worker, "_client", lambda token=None, movie=False: Client())
    first = worker.entries("https://www.dailywire.com/show/example", limit=1)
    second = worker.entries("https://www.dailywire.com/show/example", cursor=first.next_cursor, limit=1)
    assert first.next_cursor and not first.complete and second.complete
    assert [first.entries[0].position, second.entries[0].position] == [1, 2]
    assert second.entries[0].group == "2026" and second.entries[0].published_at == date


def test_ytdlp_collection_page_has_bounded_cursor(monkeypatch):
    from vodloft_source_ytdlp import worker
    options = []
    class FakeYDL:
        def __init__(self, settings):
            options.append(settings)
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def extract_info(self, url, download=False):
            count = 3 if len(options) == 1 else 1
            return {"_type": "playlist", "entries": [{"id": str(i), "title": str(i),
                "webpage_url": f"https://example.com/watch/{i}"} for i in range(count)]}
    monkeypatch.setattr(worker.yt_dlp, "YoutubeDL", FakeYDL)
    first = worker.entries("https://example.com/list/one", limit=2)
    second = worker.entries("https://example.com/list/one", first.next_cursor, limit=2)
    assert first.next_cursor == "2" and not first.complete and second.complete
    assert options[1]["playliststart"] == 3 and second.entries[0].position == 3


def test_source_search_is_a_preview_and_does_not_import(library, monkeypatch):
    client, sessions, _, gateway, _ = library
    from source_contracts import SourceSearchItem, SourceSearchPage
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1", capabilities={"search"})])
    monkeypatch.setattr(gateway.SourceGateway, "search", lambda self, source_id, query, **kw:
        SourceSearchPage(items=[SourceSearchItem(reference=ref("example.com", "found"),
            kind="video", title="Found")]))
    response = client.get("/api/vodloft/sources/fixture/search?query=Found")
    assert response.status_code == 200 and response.json()["items"][0]["title"] == "Found"
    with sessions() as session:
        assert session.scalars(select(MediaItem)).all() == []


def test_dailywire_search_catalogue_pages(monkeypatch):
    from types import SimpleNamespace
    from vodloft_source_dailywire import worker
    show = SimpleNamespace(title="Example Show", author_name="A", description=None,
        thumbnail_portrait_path=None, slug="show", dw_id="1")
    movie = SimpleNamespace(title="Example Movie", author_name="B", description=None,
        thumbnail_portrait_path=None, slug="movie", dw_id="2")
    catalog = SimpleNamespace(shows=[show], movies=[movie])
    monkeypatch.setattr(worker, "_client", lambda token=None, movie=False:
        SimpleNamespace(get_catalog=lambda: catalog))
    first = worker.search("example", limit=1)
    second = worker.search("example", cursor=first.next_cursor, limit=1)
    assert first.next_cursor == "1" and second.next_cursor is None
    assert {first.items[0].kind, second.items[0].kind} == {"collection", "movie"}


def test_item_capability_blocks_inapplicable_download(library, monkeypatch):
    client, _, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "no-download"),
        title="Read only", capabilities=set())
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profile = client.post("/api/vodloft/profiles", json={"name": "Read only", "domain": "example.com",
        "output_template": "/downloads/readonly/{{ title }}.ext"}).json()["id"]
    assert client.post(f"/api/vodloft/library/{item_id}/download",
        json={"profile_id": profile}).status_code == 409
    assert client.get(f"/api/vodloft/library/{item_id}/progress").status_code == 200


def test_unavailable_download_root_does_not_start_a_replacement(library, monkeypatch, tmp_path):
    client, _, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "storage"), title="Storage")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Storage",
        "domain": "example.com", "output_template": "/downloads/storage/{{ title }}.ext"}).json()["id"]
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path / "unmounted")
    response = client.post(f"/api/vodloft/library/{item_id}/download", json={"profile_id": profile_id})
    assert response.status_code == 503


def test_domain_profile_can_be_prepared_before_media_import(library):
    client, _, _, _, _ = library
    response = client.post("/api/vodloft/profiles", json={"name": "Prepared",
        "domain": "Example.ORG", "output_template": "/downloads/prepared/{{ title }}.ext"})
    assert response.status_code == 201, response.text
    assert response.json()["domain"] == "example.org"
    assert client.post("/api/vodloft/profiles", json={"name": "Invalid",
        "domain": "127.0.0.1", "output_template": "/downloads/invalid/{{ title }}.ext"}).status_code == 422


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


def test_bundle_rejects_unlisted_wheels_and_update_policy_channels(monkeypatch, tmp_path):
    from backend.source_manager import runtime
    monkeypatch.setenv("VODLOFT_SOURCE_RUNTIME_ROOT", str(tmp_path / "runtimes"))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "pinned.whl").write_bytes(b"pinned")
    (bundle / "extra.whl").write_bytes(b"unlisted")
    import hashlib
    (bundle / "release.json").write_text(json.dumps({"source_id": "yt-dlp", "version": "1.0.0",
        "wheels": {"pinned.whl": hashlib.sha256(b"pinned").hexdigest()}}))
    with pytest.raises(ValueError, match="undeclared"):
        runtime.install_bundle("yt-dlp", bundle)
    assert runtime.set_policy("yt-dlp", True, None, "beta")["channel"] == "beta"
    with pytest.raises(ValueError, match="policy"):
        runtime.set_policy("yt-dlp", True, None, "untrusted")


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


def test_source_download_events_reach_gateway(tmp_path):
    from backend.source_manager.gateway import SourceGateway
    worker = tmp_path / "worker.py"
    worker.write_text("import json,sys\njson.load(sys.stdin)\n"
        "print(json.dumps({'event': {'percent': 47}}), file=sys.stderr, flush=True)\n"
        "print(json.dumps({'filename': 'media.mp4', 'size': 7}))\n")
    seen = []
    result = SourceGateway({"fixture": [sys.executable, str(worker)]}).call(
        "fixture", "download", on_progress=seen.append)
    assert result == {"filename": "media.mp4", "size": 7}
    assert seen == [47]


def test_source_progress_updates_job_operation(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "progress"),
        title="Progress", capabilities={"download"})
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Progress",
        "domain": "example.com", "output_template": "/downloads/progress/{{ title }}.ext"}).json()["id"]
    job_id, _, _ = router.queue_download(item_id, profile_id)
    def download(self, source_id, url, staging, **kwargs):
        kwargs["on_progress"](50)
        assert client.get(f"/api/vodloft/jobs/{job_id}").json()["progress"] == 49
        assert client.get("/api/vodloft/jobs").json()[0]["progress"] == 49
        output = Path(staging) / "media.mp4"
        output.write_bytes(b"media")
        return DownloadResult(filename=output.name, size=5)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    router._run_download(job_id)
    assert client.get(f"/api/vodloft/jobs/{job_id}").json()["progress"] == 100


def test_nested_collection_expansion_is_explicit_bounded_and_cycle_safe(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    root_ref = ref("example.com", "root")
    child_ref = ref("example.com", "child")
    other_ref = ref("example.com", "other")
    snapshots = {
        root_ref.url: MediaSnapshot(kind="collection", reference=root_ref, title="Root", entries=[
            EntrySnapshot(reference=child_ref, kind="collection", title="Child", position=1),
            EntrySnapshot(reference=other_ref, kind="collection", title="Other", position=2)]),
        child_ref.url: MediaSnapshot(kind="collection", reference=child_ref, title="Child", entries=[
            EntrySnapshot(reference=root_ref, kind="collection", title="Root", position=1)]),
        other_ref.url: MediaSnapshot(kind="collection", reference=other_ref, title="Other"),
    }
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshots[url])
    root_id = client.post("/api/vodloft/import", json={
        "snapshot": snapshots[root_ref.url].model_dump(mode="json")}).json()["id"]
    assert client.post(f"/api/vodloft/library/{root_id}/refresh?expand_depth=4").status_code == 422
    ordinary = client.post(f"/api/vodloft/library/{root_id}/refresh").json()
    assert "nested_expansion" not in ordinary
    result = client.post(f"/api/vodloft/library/{root_id}/refresh?expand_depth=2&max_nested=1")
    assert result.status_code == 200, result.text
    expansion = result.json()["nested_expansion"]
    assert len(expansion["refreshed_ids"]) == 1
    assert {entry["reason"] for entry in expansion["skipped"]} == {
        "Collection cycle or repeated reference", "Nested Collection limit reached"}


def test_newest_backfill_uses_publication_date_before_position(library, monkeypatch):
    client, sessions, router, gateway, automation = library
    collection = MediaSnapshot(kind="collection", reference=ref("example.com", "newest-list"),
        title="Oldest first", entries=[
            EntrySnapshot(reference=ref("example.com", "old"), title="Old", position=1,
                published_at="2020-01-01T00:00:00Z"),
            EntrySnapshot(reference=ref("example.com", "new"), title="New", position=2,
                published_at="2026-01-01T00:00:00Z")])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    collection_id = client.post("/api/vodloft/import", json={
        "snapshot": collection.model_dump(mode="json")}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Newest",
        "domain": "example.com", "output_template": "/downloads/newest/{{ title }}.ext"}).json()["id"]
    policy_id = client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={
        "name": "Latest", "local_profile_ids": [profile_id], "backfill": "newest",
        "newest_count": 1}).json()["id"]
    scheduled = automation.schedule_profile(policy_id, dispatch=False)
    assert len(scheduled["queued_job_ids"]) == 1
    with sessions() as session:
        job = session.get(AcquisitionJob, scheduled["queued_job_ids"][0])
        assert session.get(MediaItem, job.item_id).title == "New"


def test_credential_file_is_scoped_encrypted_and_bounded(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    from backend.api.endpoints.vodloft.connections import source_options
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1", capabilities={"resolve_url"},
        configuration_schema=[{"name": "cookies", "label": "Cookies", "kind": "credential_file"}])])
    content = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tsession\tprivate-value\n"
    oversized = client.post("/api/vodloft/sources/connections", json={
        "source_id": "fixture", "name": "Too large", "secrets": {"cookies": "x" * (1024 * 1024 + 1)}})
    assert oversized.status_code == 422
    response = client.post("/api/vodloft/sources/connections", json={
        "source_id": "fixture", "name": "Cookies", "secrets": {"cookies": content}})
    assert response.status_code == 201, response.text
    assert "private-value" not in response.text
    with sessions() as session:
        assert source_options(session, "fixture", response.json()["id"])["cookies"] == content
    assert "private-value" not in client.get("/api/vodloft/sources/connections").text


def test_ytdlp_uses_temporary_cookie_file_and_removes_it(monkeypatch, tmp_path):
    from vodloft_source_ytdlp import worker
    seen = []
    class FakeYdl:
        def __init__(self, options): self.options = options
        def __enter__(self):
            path = Path(self.options["cookiefile"])
            assert path.parent == tmp_path and path.read_text().startswith("# Netscape")
            seen.append(path)
            return self
        def __exit__(self, *exc): pass
        def extract_info(self, url, download=False):
            return {"id": "clip", "title": "Clip", "webpage_url": url}
    monkeypatch.setattr(worker.yt_dlp, "YoutubeDL", FakeYdl)
    worker.resolve("https://example.com/clip", cookies="# Netscape HTTP Cookie File\n", scratch=str(tmp_path))
    assert seen and not seen[0].exists()
    with pytest.raises(ValueError):
        worker.resolve("https://example.com/clip", cookies="wrong format", scratch=str(tmp_path))


def test_source_gateway_reclaims_scratch_after_worker_failure(tmp_path):
    from backend.source_manager.gateway import SourceGateway, SourceInvocationError
    worker = tmp_path / "worker.py"
    marker = tmp_path / "scratch-location"
    worker.write_text("import json,sys,pathlib\n"
        "request=json.load(sys.stdin)\n"
        "pathlib.Path(sys.argv[1]).write_text(request['scratch'])\n"
        "pathlib.Path(request['scratch'], 'credential').write_text('secret')\n"
        "raise RuntimeError('expected worker failure')\n")
    gateway = SourceGateway({"fixture": [sys.executable, str(worker), str(marker)]})
    with pytest.raises(SourceInvocationError):
        gateway.call("fixture", "resolve")
    assert not Path(marker.read_text()).exists()
