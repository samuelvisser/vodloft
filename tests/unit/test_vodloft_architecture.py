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
    for path in (root / "dailywire_api" / "src").rglob("*.py"):
        imports = [node.module or "" for node in ast.walk(ast.parse(path.read_text()))
                   if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith(("backend", "config", "dailywire_authorisation"))
                       for name in imports), path

    # Provider-specific NPO behavior is entirely inside its Source package.
    for path in (root / "source_npo" / "src" / "vodloft_source_npo").rglob("*.py"):
        imports = [alias.name for node in ast.walk(ast.parse(path.read_text()))
                   if isinstance(node, ast.Import) for alias in node.names]
        imports.extend(node.module or "" for node in ast.walk(ast.parse(path.read_text()))
                       if isinstance(node, ast.ImportFrom))
        assert not any(name.startswith(("backend", "config", "yt_dlp", "dailywire"))
                       for name in imports), path


def test_npo_is_a_registered_independent_source():
    from backend.source_manager import runtime
    configured = runtime.registry()["npo"]
    assert configured["module"] == "vodloft_source_npo.worker"
    assert configured["package"] == "vodloft-source-npo"


def test_signed_release_catalogue_rejects_tampering_and_stages_exact_wheels(monkeypatch, tmp_path):
    import base64
    import hashlib
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from backend.source_manager import release_catalog

    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()
    wheel_name = "vodloft_source_ytdlp-1.2.3-py3-none-any.whl"
    wheel = b"fixture wheelhouse content"
    document = {"source_id": "yt-dlp", "releases": [{"version": "1.2.3",
        "channel": "stable", "wheels": {wheel_name: {
            "sha256": hashlib.sha256(wheel).hexdigest(),
            "url": "https://releases.example.com/wheel.whl"}}}]}
    message = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    document["signature"] = base64.b64encode(private_key.sign(message)).decode()
    config = {"url": "https://releases.example.com/index.json", "public_key": public_key}
    monkeypatch.setattr(release_catalog, "_fetch_https", lambda url, limit:
        json.dumps(document).encode() if url == config["url"] else wheel)
    assert release_catalog._verified_releases("yt-dlp", config)[0]["version"] == "1.2.3"
    signed = document.copy()
    document = {**signed, "releases": [{**signed["releases"][0], "version": "9.9.9"}]}
    with pytest.raises(ValueError, match="signature"):
        release_catalog._verified_releases("yt-dlp", config)
    document = signed

    monkeypatch.setattr(release_catalog, "configured_catalogs", lambda: {"yt-dlp": config})
    monkeypatch.setattr(release_catalog, "runtime_root", lambda: tmp_path)
    monkeypatch.setattr(importlib.import_module("backend.source_manager.runtime"), "status", lambda: {
        "policy": {}, "installed": {"yt-dlp": []}, "active": {}})
    def installed(source, bundle, *, activate):
        assert source == "yt-dlp" and activate is True
        assert (bundle / wheel_name).read_bytes() == wheel
        assert json.loads((bundle / "release.json").read_text())["wheels"][wheel_name] == hashlib.sha256(wheel).hexdigest()
        return {"version": "1.2.3"}
    monkeypatch.setattr(importlib.import_module("backend.source_manager.runtime"), "install_bundle", installed)
    assert release_catalog.install_remote_updates() == [{"version": "1.2.3"}]


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


def test_local_roles_requests_quotas_progress_and_subscriptions_are_separate(library, monkeypatch):
    from backend.security import permissions
    from backend.db.models.vodloft import LibraryRequest, MediaDemand
    client, sessions, router, gateway, automation = library
    actor = permissions.Principal()
    monkeypatch.setattr(permissions, "principal", lambda request: actor)
    # Routers import principal once; keep them on the same identity resolver.
    for name in ("router", "requests", "feeds", "connections", "integrations", "playback"):
        module = importlib.import_module("backend.api.endpoints.vodloft." + name)
        if hasattr(module, "principal"):
            monkeypatch.setattr(module, "principal", lambda request: actor)
    collection = MediaSnapshot(kind="collection", reference=ref("example.com", "list"), title="Playlist",
        entries=[EntrySnapshot(reference=ref("example.com", key), title=key, position=i)
                 for i, key in enumerate(("first", "second"), 1)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: collection)
    collection_id = client.post("/api/vodloft/import", json={"snapshot": collection.model_dump()}).json()["id"]
    entries = client.get(f"/api/vodloft/library/{collection_id}").json()["entries"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Video", "domain": "example.com"}).json()["id"]
    actor = permissions.Principal(key="alice", username="alice", role="member", request_quota=1,
                                  auto_approve=False)
    assert client.post("/api/vodloft/sources/connections", json={}).status_code == 403
    assert client.delete(f"/api/vodloft/library/{collection_id}").status_code == 403
    assert client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={}).status_code == 403
    response = client.post(f"/api/vodloft/library/{entries[0]['id']}/requests", json={"profile_id": profile_id})
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["state"] == "pending" and first["job_id"] is None
    duplicate = client.post(f"/api/vodloft/library/{entries[0]['id']}/requests", json={"profile_id": profile_id})
    assert duplicate.json()["id"] == first["id"]
    assert client.post(f"/api/vodloft/library/{entries[1]['id']}/requests", json={"profile_id": profile_id}).status_code == 429
    assert client.post(f"/api/vodloft/requests/{first['id']}/approve").status_code == 403
    assert client.put(f"/api/vodloft/library/{entries[0]['id']}/progress", json={"seconds": 42}).status_code == 200
    alice_feed = client.post(f"/api/vodloft/library/{collection_id}/feed").json()["url"]
    actor = permissions.Principal(key="bob", username="bob", role="member", can_subscribe=False)
    assert client.get("/api/vodloft/requests").json() == []
    assert client.get(f"/api/vodloft/library/{entries[0]['id']}/progress").json()["seconds"] == 0
    assert client.delete(f"/api/vodloft/requests/{first['id']}").status_code == 404
    assert client.post(f"/api/vodloft/library/{collection_id}/feed").status_code == 403
    actor = permissions.Principal(key="bob", username="bob", role="member")
    bob_feed = client.post(f"/api/vodloft/library/{collection_id}/feed").json()["url"]
    assert bob_feed != alice_feed
    actor = permissions.Principal(key="alice", username="alice", role="member")
    assert client.delete(f"/api/vodloft/requests/{first['id']}").status_code == 204
    with sessions() as session:
        assert session.get(LibraryRequest, first["id"]).state == "canceled"
        assert session.scalar(select(MediaDemand.id)) is None


@pytest.fixture
def library(monkeypatch, tmp_path):
    router = importlib.import_module("backend.api.endpoints.vodloft.router")
    profiles = importlib.import_module("backend.api.endpoints.vodloft.profiles")
    automation = importlib.import_module("backend.api.endpoints.vodloft.automation")
    feeds = importlib.import_module("backend.api.endpoints.vodloft.feeds")
    connections = importlib.import_module("backend.api.endpoints.vodloft.connections")
    integrations = importlib.import_module("backend.api.endpoints.vodloft.integrations")
    requests = importlib.import_module("backend.api.endpoints.vodloft.requests")
    permissions = importlib.import_module("backend.security.permissions")
    finalization = importlib.import_module("backend.services.vodloft_finalization")
    gateway = importlib.import_module("backend.source_manager.gateway")
    load_database_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, autoflush=False)
    for module in (router, profiles, automation, feeds, connections, integrations, finalization, requests, permissions):
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
        head = client.head(enclosure.attrib["url"])
        assert head.status_code == 200 and head.content == b"" and int(head.headers["content-length"]) > 0


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


def test_interactive_authentication_keeps_credentials_scoped_and_renews_privately(library, monkeypatch):
    client, sessions, _, gateway, _ = library
    connections = importlib.import_module("backend.api.endpoints.vodloft.connections")
    clock = [1000.0]
    monkeypatch.setattr(connections, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(gateway.SourceGateway, "__init__", lambda self, commands=None:
        setattr(self, "commands", commands or {"fixture": ["fixture-runtime"]}))
    monkeypatch.setattr(gateway.SourceGateway, "manifests", lambda self: [SourceManifest(
        source_id="fixture", display_name="Fixture", version="1", capabilities={"authentication"},
        configuration_schema=[{"name": "access_token", "label": "Token", "kind": "secret"}])])
    calls = []
    def call(self, source, operation, **options):
        calls.append((operation, options, self.commands[source]))
        if operation == "auth_start":
            return {"status": "pending", "interval": 2, "expires_at": 1600,
                "private_state": {"device_code": "private-device"},
                "challenge": {"kind": "device_code", "message": "Authorize", "user_code": "PUBLIC",
                    "verification_url": "https://account.example.com/device"}}
        if operation == "auth_poll":
            assert options["private_state"] == {"device_code": "private-device"}
            return {"status": "authorized", "expires_at": 1100,
                "private_state": {"refresh_token": "private-refresh"},
                "configuration": {"access_token": "private-access"}}
        assert operation == "auth_refresh" and options["private_state"]["refresh_token"] == "private-refresh"
        return {"status": "authorized", "expires_at": 2000,
            "private_state": {"refresh_token": "rotated-refresh"},
            "configuration": {"access_token": "renewed-access"}}
    monkeypatch.setattr(gateway.SourceGateway, "call", call)
    account = client.post("/api/vodloft/sources/connections", json={"source_id": "fixture", "name": "Account"}).json()["id"]
    other = client.post("/api/vodloft/sources/connections", json={"source_id": "fixture", "name": "Other"}).json()["id"]
    response = client.post(f"/api/vodloft/sources/connections/{account}/authenticate")
    assert response.status_code == 200 and response.json()["challenge"]["user_code"] == "PUBLIC"
    assert "private-" not in response.text
    assert client.get(f"/api/vodloft/sources/connections/{account}/authentication").json()["status"] == "pending"
    assert len(calls) == 1  # Server enforces the advertised polling interval.
    clock[0] = 1003
    assert client.get(f"/api/vodloft/sources/connections/{account}/authentication").json()["status"] == "authorized"
    assert "private-" not in client.get("/api/vodloft/sources/connections").text
    with sessions() as session:
        assert connections.source_options(session, "fixture", account) == {"access_token": "private-access"}
        assert connections.source_options(session, "fixture", other) == {}
    clock[0] = 1060
    with sessions() as session:
        assert connections.source_options(session, "fixture", account) == {"access_token": "renewed-access"}
    assert calls[-1][2] == ["fixture-runtime"]
    assert client.delete(f"/api/vodloft/sources/connections/{account}/authentication").status_code == 204
    with sessions() as session:
        assert connections.source_options(session, "fixture", account) == {}


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

    def extractor_failure(*args, **kwargs):
        raise gateway.SourceInvocationError("runtime_error",
            "fixture Source failed while extracting this URL",
            source_id="fixture", operation="resolve")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", extractor_failure)
    response = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")})
    assert response.status_code == 502
    assert response.headers["X-VodLoft-Source-Error"] == "runtime_error"
    assert response.headers["X-VodLoft-Source"] == "fixture"
    assert response.headers["X-VodLoft-Source-Operation"] == "resolve"
    assert response.json()["detail"] == "fixture Source failed while extracting this URL"


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


@pytest.mark.parametrize("path", ["/feeds/vodloft/very-secret/media/1/audio.mp3",
    "/api/vodloft/stream/very-secret", "/api/vodloft/stream/very-secret/segment/abcdef",
    "/api/vodloft/streams/very-secret"])
def test_feed_token_is_redacted_from_access_log(path):
    import logging
    from backend.feed_logging import RedactFeedToken
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", path, "1.1", 200), None)
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
    season = SimpleNamespace(dw_id="season-1", name="2026", slug="2026")
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


def test_ytdlp_unexpected_extractor_failure_is_not_media_unavailable():
    from yt_dlp.utils import DownloadError, ExtractorError
    from vodloft_source_ytdlp import worker

    unexpected = DownloadError(
        "ERROR: parser failed; please report this issue on https://github.com/yt-dlp/yt-dlp/issues")
    error = worker._source_error(unexpected)
    assert error.code == "runtime_error"
    assert error.message == "yt-dlp extractor failed"

    expected = ExtractorError("Media is unavailable", expected=True)
    error = worker._source_error(expected)
    assert error.code == "unavailable"


def test_npo_source_prefers_api_and_falls_back_to_bounded_crawler(monkeypatch):
    from vodloft_source_npo import worker

    program = {
        "productId": "NPO_TEST_1", "guid": "program-guid", "slug": "episode-one",
        "title": "Episode one", "firstBroadcastDate": 1760000000,
        "series": {"slug": "een-huis-vol", "title": "Een huis vol"},
        "season": {"slug": "seizoen-1", "seasonKey": 1},
        "programKey": 1,
    }

    class ApiClient:
        def series_detail(self, slug):
            assert slug == "een-huis-vol"
            return {"guid": "series-guid", "slug": slug, "title": "Een huis vol",
                    "type": "timeless_series"}
        def series_seasons(self, slug, series_type):
            assert series_type == "timeless_series"
            return [{"guid": "season-guid", "slug": "seizoen-1", "seasonKey": 1}]
        def programs_by_season(self, guid):
            assert guid == "season-guid"
            return [program]
        def programs_by_series(self, guid, limit=250):
            raise AssertionError("season API should be preferred")

    monkeypatch.setattr(worker, "_client", lambda *args: ApiClient())
    monkeypatch.setattr(worker.crawler, "series",
        lambda *args: (_ for _ in ()).throw(AssertionError("crawler should not run")))
    snapshot = worker.resolve("https://npo.nl/start/serie/een-huis-vol")
    assert snapshot.kind == "collection"
    assert snapshot.reference.upstream_id == "series-guid"
    assert snapshot.entries[0].reference.upstream_id == "NPO_TEST_1"
    assert snapshot.entries[0].group == "1"

    class BrokenApi(ApiClient):
        def series_detail(self, slug):
            raise worker.ApiUnavailable("fixture API outage")

    monkeypatch.setattr(worker, "_client", lambda *args: BrokenApi())
    monkeypatch.setattr(worker.crawler, "series", lambda url, client: (
        {"guid": "crawler-series", "slug": "een-huis-vol", "title": "Crawler title"},
        [{**program, "productId": "NPO_CRAWLER_1"}],
    ))
    fallback = worker.resolve("https://npo.nl/start/serie/een-huis-vol")
    assert fallback.title == "Crawler title"
    assert fallback.reference.upstream_id == "crawler-series"
    assert fallback.entries[0].reference.upstream_id == "NPO_CRAWLER_1"


def test_npo_login_and_drm_handling_keep_credentials_private(monkeypatch):
    import time
    from vodloft_source_npo.client import DRMProtected, NPOClient

    client = NPOClient("member@example.com", "super-secret")
    session_calls = 0
    posted = []

    def fake_request(url, **kwargs):
        nonlocal session_calls
        data = kwargs.get("data")
        if url.endswith("/api/auth/session"):
            session_calls += 1
            value = {} if session_calls == 1 else {
                "tokenExpiresAt": time.time() + 3600, "hasSubscription": True}
            return url, json.dumps(value).encode()
        if url.endswith("/api/auth/csrf"):
            return url, b'{"csrfToken":"csrf-token"}'
        if url.endswith("/api/auth/signin/npo-id"):
            return "https://id.npo.nl/account/login", (
                b'<input name="ReturnUrl" value="/callback">'
                b'<input name="__RequestVerificationToken" value="verify">')
        if url == "https://id.npo.nl/account/login":
            posted.append(data.decode())
            return "https://npo.nl/start/api/auth/session", b"ok"
        raise AssertionError(url)

    monkeypatch.setattr(client, "_request", fake_request)
    session = client.login()
    assert session["hasSubscription"] is True
    assert posted and "EmailAddress=member%40example.com" in posted[0]
    assert "Password=super-secret" in posted[0]
    assert "super-secret" not in json.dumps(session)

    anonymous = NPOClient()
    monkeypatch.setattr(anonymous, "_player_token", lambda *args, **kwargs: "jwt")
    monkeypatch.setattr(anonymous, "_request", lambda *args, **kwargs: (
        "https://prod.npoplayer.nl/stream-link",
        json.dumps({"stream": {
            "streamURL": "https://cdn.example/media.mpd",
            "drm": {"licenseUrl": "https://license.example/widevine"},
        }}).encode(),
    ))
    with pytest.raises(DRMProtected):
        anonymous.playback("NPO_TEST_1", "https://npo.nl/start/video/test")


def test_npo_crawler_reads_next_data_and_same_series_links():
    from vodloft_source_npo import crawler

    html = """
    <html><head>
      <meta property="og:title" content="Een huis vol">
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"program":{"productId":"NPO_1","slug":"episode-one",
        "title":"Episode one","series":{"slug":"een-huis-vol"},
        "season":{"slug":"seizoen-1"}}}}}
      </script>
    </head><body>
      <a href="/start/serie/een-huis-vol/seizoen-1/episode-one/afspelen">episode</a>
      <a href="https://example.com/not-allowed">outside</a>
    </body></html>
    """
    page = crawler.parse("https://npo.nl/start/serie/een-huis-vol", html)
    assert page.title == "Een huis vol"
    assert any(record.get("productId") == "NPO_1" for record in page.records)
    assert page.links == [
        "https://npo.nl/start/serie/een-huis-vol/seizoen-1/episode-one/afspelen"]


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
    assert router.queue_download(item_id, profile_id)[1] == 'suppressed'
    assert client.post(f'/api/vodloft/library/{item_id}/local/{profile_id}/resume').status_code == 200
    assert router.queue_download(item_id, profile_id)[2]


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
        "print(json.dumps({'event': {'stage': 'processing'}}), file=sys.stderr, flush=True)\n"
        "print(json.dumps({'filename': 'media.mp4', 'size': 7}))\n")
    seen, stages = [], []
    result = SourceGateway({"fixture": [sys.executable, str(worker)]}).call(
        "fixture", "download", on_progress=seen.append, on_stage=stages.append)
    assert result == {"filename": "media.mp4", "size": 7}
    assert seen == [47]
    assert stages == ['downloading', 'processing']


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
        assert kwargs["reference"]["upstream_id"] == "progress"
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


def test_inherited_episode_enumeration_crosses_dailywire_worker_boundary(monkeypatch):
    from backend.source_manager.dailywire_legacy import MiddlewareClient, ByShowSeason
    from backend.source_manager.gateway import SourceGateway
    from vodloft_source_dailywire import worker

    seen = []
    def call(self, source_id, operation, **options):
        seen.append((source_id, operation, options))
        return {"items": [], "next_page_url": None, "has_next": False}
    monkeypatch.setattr(SourceGateway, "call", call)
    page = MiddlewareClient(access_token="private-token").get_episodes_paginated(
        "series", ByShowSeason(season_dw_id="season", page_size=7))
    assert page.items == [] and not page.has_next
    assert seen[0][0:2] == ("dailywire", "legacy_call")
    assert seen[0][2]["args"][1] == {"type": "ByShowSeason", "fields": {
        "season_dw_id": "season", "membership_plan": None, "order_by": "CreatedAt_DESC",
        "page_number": 1, "page_size": 7, "show_offset": 0, "podcast_offset": 0}}

    class FakeClient:
        def get_episodes_paginated(self, show, selector):
            assert show == "series" and isinstance(selector, ByShowSeason)
            return SimpleNamespace(items=[], next_page_url=None, has_next=False)
    monkeypatch.setattr(worker, "_client", lambda token, movie=False: FakeClient())
    assert worker.legacy_call({"method": "get_episodes_paginated", "args": seen[0][2]["args"],
        "kwargs": {}, "access_token": "private-token"}) == {
            "items": [], "next_page_url": None, "has_next": False}


def test_upstream_hls_session_masks_lease_and_child_urls(library, monkeypatch):
    import base64
    from source_contracts import StreamLease
    from backend.api.endpoints.vodloft import playback
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(playback, "get_session", sessions)
    monkeypatch.setattr(playback, "validate_public_url", lambda url: url)
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "private-hls"), title="Stream")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={
        "snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    monkeypatch.setattr(gateway.SourceGateway, "stream_lease", lambda *args, **kw: StreamLease(
        transport="hls", url="https://cdn.example.com/secret.m3u8?sig=private",
        headers={"Authorization": "Bearer private-token"}))
    calls = []
    def fetch(self, source_id, operation, **options):
        calls.append(options)
        playlist = options["url"].endswith("m3u8?sig=private")
        payload = b"#EXTM3U\n#EXTINF:5,\nsegment.ts?sig=hidden\n" if playlist else b"segment bytes"
        return {"data": base64.b64encode(payload).decode(),
            "content_type": "application/vnd.apple.mpegurl" if playlist else "video/mp2t",
            "content_range": None, "status": 200, "url": options["url"]}
    monkeypatch.setattr(gateway.SourceGateway, "call", fetch)
    watch = client.post(f"/api/vodloft/library/{item_id}/watch")
    assert watch.status_code == 200, watch.text
    assert watch.json()["transport"] == "hls" and "private" not in watch.text
    manifest = client.get(watch.json()["url"])
    assert manifest.status_code == 200
    assert "cdn.example.com" not in manifest.text and "private" not in manifest.text
    child_url = manifest.text.splitlines()[-1]
    assert client.get(child_url).content == b"segment bytes"
    assert calls[-1]["headers"]["Authorization"] == "Bearer private-token"
    with sessions() as session:
        from backend.db.models.vodloft import PlaybackSession
        stored = session.scalar(select(PlaybackSession))
        assert "private-token" not in stored.lease_ciphertext


def test_hls_child_renews_signed_uri_and_keeps_one_representation(library, monkeypatch):
    import base64
    from datetime import datetime, timedelta, timezone
    from source_contracts import StreamLease
    from backend.api.endpoints.vodloft import playback
    from backend.db.models.vodloft import PlaybackSession, PlaybackSegment
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(playback, "get_session", sessions)
    monkeypatch.setattr(playback, "validate_public_url", lambda url: url)
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "renew"), title="Renewable")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    revision = ["first"]
    representation = ["same-format"]
    monkeypatch.setattr(gateway.SourceGateway, "stream_lease", lambda *args, **kw: StreamLease(
        transport="hls", url=f"https://cdn.example.com/master.m3u8?sig={revision[0]}",
        renewable=True, representation_id=representation[0],
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()))
    calls = []
    def fetch(self, source, operation, **options):
        calls.append(options["url"])
        playlist = "/master.m3u8" in options["url"]
        payload = (f"#EXTM3U\n#EXTINF:5,\nsegment.ts?sig={revision[0]}\n".encode()
            if playlist else b"segment-" + revision[0].encode())
        return {"data": base64.b64encode(payload).decode(), "url": options["url"],
            "content_type": "application/vnd.apple.mpegurl" if playlist else "video/mp2t", "status": 200}
    monkeypatch.setattr(gateway.SourceGateway, "call", fetch)
    watch = client.post(f"/api/vodloft/library/{item_id}/watch").json()
    first = client.get(watch["url"])
    child = first.text.splitlines()[-1]
    assert client.get(watch["url"]).text == first.text
    with sessions() as session:
        assert len(session.scalars(select(PlaybackSegment)).all()) == 1
        stored = session.scalar(select(PlaybackSession))
        lease = playback._unseal(stored.lease_ciphertext)
        lease["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        stored.lease_ciphertext = playback._seal(lease)
        session.commit()
    revision[0] = "renewed"
    assert client.get(child).content == b"segment-renewed"
    assert calls[-1] == "https://cdn.example.com/segment.ts?sig=renewed"
    with sessions() as session:
        stored = session.scalar(select(PlaybackSession))
        lease = playback._unseal(stored.lease_ciphertext)
        lease["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        stored.lease_ciphertext = playback._seal(lease)
        session.commit()
    representation[0] = "different-edit"
    assert client.get(child).status_code == 409


def test_profile_representation_is_frozen_and_partitions_artifact_reuse(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "tracks"), title="Tracks")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profiles = []
    for language in ("en", "nl"):
        response = client.post("/api/vodloft/profiles", json={"name": language, "domain": "example.com",
            "output_template": f"/downloads/{language}/{{{{ title }}}}.ext",
            "representation": {"languages": [language], "subtitles": [language], "container": "mkv"}})
        assert response.status_code == 201, response.text
        profiles.append(response.json()["id"])
    seen = []
    def download(self, source, url, staging, **options):
        seen.append(options["representation"])
        path = Path(staging) / "media.mkv"
        path.write_bytes(options["representation"]["languages"][0].encode())
        return DownloadResult(filename=path.name, size=path.stat().st_size)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    for profile_id in profiles:
        job_id, _, created = router.queue_download(item_id, profile_id)
        assert created
        router._run_download(job_id)
    assert [policy["languages"] for policy in seen] == [["en"], ["nl"]]
    with sessions() as session:
        assert len({artifact.representation_key for artifact in session.scalars(select(Artifact)).all()}) == 2


def test_retention_preserves_shared_demands_and_active_local_session(library, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete
    from backend.db.models.vodloft import ArtifactPlacement, MediaDemand, PlaybackSession
    from backend.api.endpoints.vodloft import playback
    from backend.services import vodloft_retention
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(playback, "get_session", sessions)
    monkeypatch.setattr(vodloft_retention, "get_session", sessions)
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "shared-copy"), title="Shared")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profile_id = client.post("/api/vodloft/profiles", json={"name": "Shared",
        "domain": "example.com", "output_template": "/downloads/shared/{{ title }}.ext"}).json()["id"]
    canonical = tmp_path / "vodloft" / f"{item_id}-1.mp4"
    canonical.parent.mkdir()
    canonical.write_bytes(b"shared media")
    presented = tmp_path / "shared.mp4"
    presented.write_bytes(b"shared media")
    with sessions() as session:
        artifact = Artifact(item_id=item_id, profile_id=profile_id, path=str(canonical),
            size=canonical.stat().st_size, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        session.add(artifact); session.flush()
        session.add(ArtifactPlacement(artifact_id=artifact.id, profile_id=profile_id,
            path=str(presented)))
        for owner in (1, 2):
            session.add(MediaDemand(item_id=item_id, profile_id=profile_id,
                owner_kind="policy", owner_id=owner))
        session.commit()
    assert vodloft_retention.reconcile(grace_hours=0) == 0
    with sessions() as session:
        session.execute(delete(MediaDemand).where(MediaDemand.owner_id == 1)); session.commit()
    assert vodloft_retention.reconcile(grace_hours=0) == 0
    watch = client.post(f"/api/vodloft/library/{item_id}/watch")
    assert watch.json()["transport"] == "file"
    with sessions() as session:
        session.execute(delete(MediaDemand).where(MediaDemand.owner_id == 2)); session.commit()
    assert vodloft_retention.reconcile(grace_hours=0) == 0
    assert client.get(watch.json()["url"]).content == b"shared media"
    with sessions() as session:
        session.scalar(select(PlaybackSession)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert vodloft_retention.reconcile(grace_hours=0) == 1
    assert not canonical.exists() and not presented.exists()


def test_compatible_profiles_share_one_artifact_without_crossing_source_accounts(library, monkeypatch):
    from datetime import datetime, timezone
    from backend.db.models.vodloft import ArtifactPlacement
    from backend.services import vodloft_retention
    client, sessions, router, gateway, _ = library
    monkeypatch.setattr(vodloft_retention, "get_session", sessions)
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "dedup"), title="Shared")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={
        "snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    profiles = [client.post("/api/vodloft/profiles", json={"name": f"Layout {index}",
        "domain": "example.com", "output_template": f"/downloads/layout-{index}/{{{{ title }}}}.ext"}).json()["id"]
        for index in (1, 2)]
    def download(self, source_id, url, staging, **options):
        output = Path(staging) / "media.mp4"
        output.write_bytes(b"one representation")
        return DownloadResult(filename=output.name, size=output.stat().st_size)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    first_job, _, created = router.queue_download(item_id, profiles[0])
    assert created
    router._run_download(first_job)
    assert router.queue_download(item_id, profiles[1]) == (None, "available", False)
    with sessions() as session:
        artifacts = session.scalars(select(Artifact)).all()
        placements = session.scalars(select(ArtifactPlacement)).all()
        assert len(artifacts) == 1 and len(placements) == 2
        assert {placement.profile_id for placement in placements} == set(profiles)
        artifacts[0].created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        canonical = Path(artifacts[0].path)
        first_path = Path(next(p.path for p in placements if p.profile_id == profiles[0]))
        second_path = Path(next(p.path for p in placements if p.profile_id == profiles[1]))
        session.commit()
    assert client.delete(f"/api/vodloft/library/{item_id}/local/{profiles[0]}").status_code == 200
    assert canonical.exists() and second_path.exists() and not first_path.exists()
    with sessions() as session:
        assert len(session.scalars(select(Artifact)).all()) == 1
    account = client.post("/api/vodloft/sources/connections", json={"source_id": "fixture",
        "name": "Other account", "secrets": {"access_token": "private"}}).json()["id"]
    client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json"),
        "connection_id": account})
    references = client.get(f"/api/vodloft/library/{item_id}").json()["references"]
    other = next(reference["id"] for reference in references if reference["connection_id"] == account)
    third = client.post("/api/vodloft/profiles", json={"name": "Different account",
        "domain": "example.com", "output_template": "/downloads/other-account/{{ title }}.ext"}).json()["id"]
    new_job, state, created = router.queue_download(item_id, third, reference_id=other)
    assert created and state == "queued" and new_job != first_job


def test_live_admission_requires_download_policy_and_survives_archive_transition(library, monkeypatch, tmp_path):
    from backend.api.endpoints.vodloft import feeds
    from backend.db.models.vodloft import LiveAdmission
    client, sessions, router, gateway, _ = library
    child = EntrySnapshot(reference=ref("example.com", "live"), title="Broadcast",
        position=1, is_live=True, capabilities={"download", "stream_lease"})
    collection = MediaSnapshot(kind="collection", reference=SourceMediaReference(
        source_id="fixture", domain="example.com", namespace="list", upstream_id="live-list",
        url="https://example.com/list/live-list"), title="Broadcasts", entries=[child])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: collection)
    collection_id = client.post("/api/vodloft/import", json={
        "snapshot": collection.model_dump(mode="json")}).json()["id"]
    strict = client.post(f"/api/vodloft/library/{collection_id}/stream-profiles", json={
        "name": "Live audio", "format": "audio", "include_live": True,
        "local_only": True}).json()["id"]
    assert client.get(f"/api/vodloft/stream-profiles/{strict}/admissions").json() == []
    audio_profile = client.post("/api/vodloft/profiles", json={"name": "Live MP3",
        "domain": "example.com", "preferred_format": "format_audio_only",
        "output_template": "/downloads/live/{{ title }}.ext"}).json()["id"]
    policy = client.post(f"/api/vodloft/library/{collection_id}/download-profiles", json={
        "name": "Archive live", "local_profile_ids": [audio_profile], "backfill": "all"})
    assert policy.status_code == 201
    queued = []
    monkeypatch.setattr(router, "queue_download", lambda *args, **kw:
        (queued.append((args, kw)), (None, "queued", False))[1])
    feeds.reconcile_live_admissions(collection_id)
    with sessions() as session:
        admission = session.scalar(select(LiveAdmission))
        assert admission.state == "upstream"
        item_id = admission.item_id
    assert queued and queued[0][1]["policy_id"] == policy.json()["id"]
    child.is_live = False
    client.post("/api/vodloft/import", json={"snapshot": collection.model_dump(mode="json")})
    assert client.get(f"/api/vodloft/stream-profiles/{strict}/admissions").json()[0]["state"] == "upstream"
    local = tmp_path / "vodloft" / "live.mp3"
    local.parent.mkdir(exist_ok=True)
    local.write_bytes(b"archived audio")
    with sessions() as session:
        session.add(Artifact(item_id=item_id, profile_id=audio_profile,
            path=str(local), size=local.stat().st_size))
        session.commit()
    feeds.reconcile_live_admissions(collection_id)
    assert client.get(f"/api/vodloft/stream-profiles/{strict}/admissions").json()[0]["state"] == "local"


def test_jellyfin_presentation_freezes_episode_number_and_writes_explicit_metadata(tmp_path):
    from backend.api.endpoints.vodloft.integrations import _write_nfo
    from backend.db.models.vodloft import MediaServerExport
    item = SimpleNamespace(id=32, kind="video", title="Source title", user_title="Library title",
        description="Description", user_description=None, duration=300,
        published_at=None)
    export = MediaServerExport(season_number=2, episode_number=7)
    path = tmp_path / "episode.mp4"
    path.write_bytes(b"media")
    _write_nfo(path, item, export, "Collection title")
    tree = ElementTree.parse(path.with_suffix(".nfo"))
    assert tree.findtext("title") == "Library title"
    assert tree.findtext("showtitle") == "Collection title"
    assert tree.findtext("season") == "2" and tree.findtext("episode") == "7"


def test_plex_presentation_uses_actual_scanner_agent_and_server_identity(monkeypatch):
    from backend.api.endpoints.vodloft import integrations
    from backend.db.models.vodloft import MediaServerExport
    target = SimpleNamespace(kind="plex", library_id="4", base_url="http://plex.local:32400")
    requested = []
    def request(_target, method, path):
        requested.append(path)
        if path == "/library/sections":
            return (b'<MediaContainer><Directory key="4" title="Web videos" '
                b'scanner="Plex Video Files Scanner" agent="com.plexapp.agents.none" '
                b'type="movie" /></MediaContainer>')
        assert path == "/identity"
        return b'<MediaContainer machineIdentifier="0123456789abcdef0123456789abcdef" />'
    monkeypatch.setattr(integrations, "_request", request)
    capabilities = integrations.discover(target)
    assert requested == ["/library/sections", "/identity"]
    assert capabilities["presentation"] == "personal_media"
    export = MediaServerExport(remote_id="42", remote_server_id=capabilities["machine_id"])
    assert integrations._external_url(target, export).endswith(
        "/details?key=%2Flibrary%2Fmetadata%2F42")


def test_audiobookshelf_item_mapping_and_progress_pull_never_rewinds(library, monkeypatch, tmp_path):
    from backend.api.endpoints.vodloft import integrations
    from backend.db.models.vodloft import ArtifactPlacement, MediaServerExport, PlaybackProgress
    client, sessions, _, gateway, _ = library
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "podcast-ep"), title="Episode")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *args, **kw: snapshot)
    item_id = client.post("/api/vodloft/import", json={
        "snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    target = client.post("/api/vodloft/integrations", json={"kind": "audiobookshelf",
        "name": "Podcasts", "base_url": "http://localhost:13378", "library_id": "lib_1",
        "local_prefix": str(tmp_path), "server_prefix": "/podcasts", "api_key": "private"})
    assert target.status_code == 201, target.text
    path = tmp_path / "episode.mp3"
    path.write_bytes(b"audio")
    with sessions() as session:
        artifact = Artifact(item_id=item_id, path=str(tmp_path / "vodloft" / "episode.mp3"), size=5)
        session.add(artifact); session.flush()
        placement = ArtifactPlacement(artifact_id=artifact.id, profile_id=None, path=str(path))
        # A delivery placement normally has a Local Media Profile. Its ID is
        # used only as a foreign key in this in-memory mapping fixture.
        from backend.db.models.local_media_profile import DomainLocalMediaProfile
        from backend.db.models.vodloft import Domain
        domain = session.scalar(select(Domain).where(Domain.hostname == "example.com"))
        profile = DomainLocalMediaProfile(name="Podcast audio", slug="podcast-audio",
            domain_id=domain.id, preferred_format="format_audio_only",
            output_template="/downloads/podcast/{{ title }}.ext", applicable_kinds=["video"],
            enabled=True, delivery_target_ids=[])
        session.add(profile); session.flush()
        placement.profile_id = profile.id
        session.add(placement); session.flush()
        export = MediaServerExport(placement_id=placement.id, target_id=target.json()["id"],
            remote_id="li_podcast", remote_episode_id="ep_episode", state="available", attempts=1)
        session.add(export)
        session.add(PlaybackProgress(user_key="admin", item_id=item_id, seconds=120, completed=False))
        session.commit()
        export_id = export.id
    mappings = client.get(f"/api/vodloft/library/{item_id}/integrations").json()
    assert mappings[0]["remote_episode_id"] == "ep_episode"
    assert mappings[0]["url"] == "http://localhost:13378/item/li_podcast"
    monkeypatch.setattr(integrations, "_request", lambda target, method, path, **kw:
        json.dumps({"id": "abs-admin"} if path == "/api/me" else {"currentTime": 60, "isFinished": True}).encode())
    assert client.post(f"/api/vodloft/integrations/exports/{export_id}/progress/pull").status_code == 409
    mapped = client.put(f"/api/vodloft/integrations/{target.json()['id']}/users", json={
        "user_key": "admin", "remote_user_id": "abs-admin", "api_key": "listening-token"})
    assert mapped.status_code == 200 and "listening-token" not in mapped.text
    pulled = client.post(f"/api/vodloft/integrations/exports/{export_id}/progress/pull")
    assert pulled.status_code == 200, pulled.text
    assert pulled.json() == {"seconds": 120, "completed": True}


def test_independent_source_bundle_install_health_failure_and_rollback(library, monkeypatch, tmp_path):
    import hashlib
    import zipfile
    from backend.source_manager import runtime
    _, sessions, _, _, _ = library
    monkeypatch.setattr(importlib.import_module('backend.db'), 'get_session', sessions)
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'sources': {'third': {'module': 'fixture_source.worker',
        'package': 'fixture-source-runtime'}}}))
    monkeypatch.setenv('VODLOFT_SOURCE_REGISTRY', str(registry))
    monkeypatch.setenv('VODLOFT_SOURCE_RUNTIME_ROOT', str(tmp_path / 'runtimes'))

    def bundle(version, engine, healthy=True):
        folder = tmp_path / version
        folder.mkdir()
        manifest = {'source_id': 'third', 'display_name': 'Third Source', 'version': '1.0.0',
            'upstream_versions': {'fixture-engine': engine}, 'capabilities': ['health', 'domain_catalogue']}
        worker = 'import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({' + repr('manifest') + ': ' + repr(manifest) + ', ' + repr('health') + ': ' + repr({'healthy': healthy}) + ', ' + repr('domains') + ': ' + repr({'items': [], 'exhaustive': True}) + '}[r["operation"]]))\n'
        wheel = folder / 'fixture_source_runtime-1.0.0-py3-none-any.whl'
        dist = 'fixture_source_runtime-1.0.0.dist-info/'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('fixture_source/__init__.py', '')
            archive.writestr('fixture_source/worker.py', worker)
            archive.writestr(dist + 'METADATA', 'Metadata-Version: 2.1\nName: fixture-source-runtime\nVersion: 1.0.0\n')
            archive.writestr(dist + 'WHEEL', 'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            archive.writestr(dist + 'RECORD', '')
        release = {'source_id': 'third', 'version': version, 'adapter_version': '1.0.0',
            'upstream_versions': {'fixture-engine': engine},
            'wheels': {wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest()}}
        (folder / 'release.json').write_text(json.dumps(release))
        return folder

    first = bundle('1.0.0+engine1', '1.0')
    release = json.loads((first / 'release.json').read_text())
    release['upstream_versions']['fixture-engine'] = '1.00'
    (first / 'release.json').write_text(json.dumps(release))
    assert runtime.install_bundle('third', first)['active'] is True
    old_command = runtime.command_for('third')[0]
    second = bundle('1.0.0+engine2', '2.0')
    assert runtime.install_bundle('third', second)['manifest']['upstream_versions'] == {'fixture-engine': '2.0'}
    assert runtime.command_for('third')[0] != old_command
    assert Path(old_command[0]).is_file()
    mismatch = bundle('1.0.0+engine4', '4.0')
    wrong_release = json.loads((mismatch / 'release.json').read_text())
    wrong_release['upstream_versions']['fixture-engine'] = '99.0'
    (mismatch / 'release.json').write_text(json.dumps(wrong_release))
    with pytest.raises(ValueError, match='upstream dependencies'):
        runtime.install_bundle('third', mismatch)
    assert '1.0.0+engine4' not in runtime.status()['installed']['third']
    saved = tmp_path / 'runtimes' / 'third' / '1.0.0+engine1' / 'release.json'
    original = saved.read_text()
    wrong_release['version'] = '1.0.0+engine1'
    saved.write_text(json.dumps(wrong_release))
    with pytest.raises(ValueError, match='upstream dependencies'):
        runtime.activate('third', '1.0.0+engine1')
    saved.write_text(original)
    assert runtime.status()['active']['third'] == '1.0.0+engine2'
    bad = bundle('1.0.0+engine3', '3.0', healthy=False)
    with pytest.raises(ValueError, match='health'):
        runtime.install_bundle('third', bad)
    assert runtime.status()['active']['third'] == '1.0.0+engine2'
    assert runtime.status()['installed']['third'] == ['1.0.0+engine1', '1.0.0+engine2']
    runtime.record_failure('third', 'test_health', ValueError('private-token'))
    assert 'private-token' not in json.dumps(runtime.status())
    runtime.rollback('third')
    assert runtime.command_for('third')[0] == old_command


def test_source_update_failure_isolated_to_one_release(library, monkeypatch, tmp_path):
    from backend.source_manager import runtime
    monkeypatch.setenv('VODLOFT_SOURCE_RUNTIME_ROOT', str(tmp_path / 'runtimes'))
    monkeypatch.setenv('VODLOFT_SOURCE_BUNDLE_DIR', str(tmp_path / 'bundles'))
    for source in ('yt-dlp', 'dailywire'):
        folder = tmp_path / 'bundles' / source / '1.0.0'
        folder.mkdir(parents=True)
        (folder / 'release.json').write_text(json.dumps({'source_id': source, 'version': '1.0.0'}))
    called = []
    def install(source, bundle, *, activate):
        called.append(source)
        if source == 'yt-dlp':
            raise ValueError('private-credential')
        return {'source_id': source, 'version': '1.0.0'}
    monkeypatch.setattr(runtime, 'install_bundle', install)
    monkeypatch.setattr(runtime, 'activate', lambda *args: {})
    results = runtime.install_bundled_updates()
    assert called == ['yt-dlp', 'dailywire']
    assert results[0]['state'] == 'failed'
    assert results[1]['source_id'] == 'dailywire'
    assert 'private-credential' not in json.dumps(runtime.status())


def test_profile_deletion_cancels_queued_work_and_preserves_shared_artifact(library, monkeypatch, tmp_path):
    from backend.db.models.vodloft import ArtifactPlacement, MediaDemand
    from backend.services import vodloft_retention
    client, sessions, router, gateway, _ = library
    monkeypatch.setattr(vodloft_retention, 'get_session', sessions)
    snapshot = MediaSnapshot(kind='video', reference=ref('example.com', 'shared-delete'), title='Shared')
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *args, **kw: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump()}).json()['id']
    ids = [client.post('/api/vodloft/profiles', json={'name': name, 'domain': 'example.com',
        'output_template': '/downloads/' + name + '/{{ title }}.ext'}).json()['id'] for name in ('one', 'two')]
    canonical = tmp_path / 'vodloft' / 'shared.mp4'
    canonical.parent.mkdir()
    canonical.write_bytes(b'shared representation')
    with sessions() as db:
        artifact = Artifact(item_id=item_id, profile_id=ids[0], path=str(canonical), size=canonical.stat().st_size)
        db.add(artifact); db.flush()
        for profile_id in ids:
            placement = tmp_path / f'{profile_id}.mp4'
            placement.write_bytes(canonical.read_bytes())
            db.add(ArtifactPlacement(artifact_id=artifact.id, profile_id=profile_id, path=str(placement)))
            db.add(MediaDemand(item_id=item_id, profile_id=profile_id, owner_kind='direct', owner_id=item_id))
        job = AcquisitionJob(item_id=item_id, reference_id=db.scalar(select(SourceReference.id).where(SourceReference.item_id == item_id)), profile_id=ids[0], state='queued', execution_spec={}, active_key=f'{item_id}:{ids[0]}')
        db.add(job); db.commit(); job_id=job.id
    assert client.delete(f'/api/vodloft/profiles/{ids[0]}').status_code == 204
    assert [p['id'] for p in client.get('/api/vodloft/profiles').json()] == [ids[1]]
    with sessions() as db:
        assert db.get(AcquisitionJob, job_id).state == 'canceled'
        assert db.scalar(select(MediaDemand.id).where(MediaDemand.profile_id == ids[0])) is None
        assert db.scalar(select(MediaDemand.id).where(MediaDemand.profile_id == ids[1])) is not None
    assert client.post(f'/api/vodloft/jobs/{job_id}/retry').status_code == 409
    assert vodloft_retention.reconcile(grace_hours=0) == 0
    assert canonical.is_file() and (tmp_path / f'{ids[1]}.mp4').is_file()
    assert not (tmp_path / f'{ids[0]}.mp4').exists()


def test_playback_session_enforces_owner_and_withdrawn_source_grant(library, monkeypatch):
    import base64
    from backend.api.endpoints.vodloft import playback
    from backend.security import permissions
    from backend.db.models.vodloft import SourceConnection
    from source_contracts import StreamLease
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(playback, 'get_session', sessions)
    monkeypatch.setattr(playback, 'validate_public_url', lambda url: url)
    with sessions() as session:
        connection = SourceConnection(source_id='fixture', name='Account')
        session.add(connection); session.commit(); connection_id = connection.id
    snapshot = MediaSnapshot(kind='video', reference=ref('example.com', 'owner'), title='Private account')
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **k: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump(mode='json'),
        'connection_id': connection_id}).json()['id']
    actor = permissions.Principal(key='alice', role='member', connection_ids=[connection_id])
    monkeypatch.setattr(permissions, 'principal', lambda request: actor)
    monkeypatch.setattr(playback, 'principal', lambda request: actor)
    monkeypatch.setattr(gateway.SourceGateway, 'stream_lease', lambda *a, **k: StreamLease(
        transport='http', url='https://cdn.example.com/media.mp4'))
    monkeypatch.setattr(gateway.SourceGateway, 'call', lambda *a, **k: {
        'data': base64.b64encode(b'media').decode(), 'url': k['url'], 'status': 200})
    watch = client.post(f'/api/vodloft/library/{item_id}/watch')
    assert watch.status_code == 200, watch.text
    url = watch.json()['url']
    assert client.get(url).content == b'media'
    actor = permissions.Principal(key='bob', role='member', connection_ids=[connection_id])
    assert client.get(url).status_code == 404
    actor = permissions.Principal(key='alice', role='member')
    assert client.get(url).status_code == 403
    actor = permissions.Principal(key='alice', role='member', connection_ids=[connection_id])
    with sessions() as session:
        session.get(SourceConnection, connection_id).enabled = False; session.commit()
    assert client.get(url).status_code == 403


def test_source_rejects_reassigned_download_identity_before_acquisition(monkeypatch, tmp_path):
    from vodloft_source_ytdlp import worker
    expected = SourceMediaReference(source_id='yt-dlp', domain='example.com', namespace='Generic',
        upstream_id='old-upload', url='https://example.com/video')
    def acquire(url, staging, format, representation, metadata, auth, verify):
        verify({'id': 'different-upload', 'webpage_url': url, 'extractor_key': 'Generic'})
        pytest.fail('Changed upstream identity must not be downloaded')
    monkeypatch.setattr(worker, 'acquire_media', acquire)
    with pytest.raises(ValueError, match='different media'):
        worker.download(expected.url, str(tmp_path), reference=expected.model_dump())


def test_management_edits_keep_secrets_and_feed_rotation_revokes_old_url(library, monkeypatch):
    from backend.api.endpoints.vodloft.connections import source_options
    from backend.api.endpoints.vodloft.integrations import _token
    from backend.db.models.vodloft import MediaServerTarget
    client, sessions, _, gateway, _ = library
    connection = client.post('/api/vodloft/sources/connections', json={
        'source_id': 'fixture', 'name': 'Old name', 'secrets': {'access_token': 'private-token'}}).json()
    edited = client.put(f"/api/vodloft/sources/connections/{connection['id']}", json={
        'source_id': 'fixture', 'name': 'New name', 'settings': {}, 'enabled': True})
    assert edited.status_code == 200 and edited.json()['has_secret']
    with sessions() as session:
        assert source_options(session, 'fixture', connection['id'])['access_token'] == 'private-token'
    removed = client.put(f"/api/vodloft/sources/connections/{connection['id']}", json={
        'source_id': 'fixture', 'name': 'New name', 'remove_secret_fields': ['access_token']})
    assert removed.status_code == 200 and not removed.json()['has_secret']
    target = client.post('/api/vodloft/integrations', json={'kind': 'jellyfin', 'name': 'Server',
        'base_url': 'http://media-server:8096', 'library_id': 'library', 'local_prefix': '/downloads',
        'server_prefix': '/media', 'api_key': 'server-secret'}).json()
    updated = client.put(f"/api/vodloft/integrations/{target['id']}", json={**target, 'name': 'Updated', 'enabled': False})
    assert updated.status_code == 200 and 'server-secret' not in updated.text
    with sessions() as session:
        assert _token(session.get(MediaServerTarget, target['id'])) == 'server-secret'
    snapshot = MediaSnapshot(kind='collection', reference=ref('example.com', 'rotate'), title='Rotatable')
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **k: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump(mode='json')}).json()['id']
    profile = client.post(f'/api/vodloft/library/{item_id}/stream-profiles', json={'name': 'Feed'}).json()
    old = client.post(f"/api/vodloft/stream-profiles/{profile['id']}/feed").json()['url']
    assert client.post(f"/api/vodloft/stream-profiles/{profile['id']}/feed").json()['url'] == old
    rotated = client.post(f"/api/vodloft/stream-profiles/{profile['id']}/feed/rotate").json()['url']
    assert client.get(old).status_code == 404 and client.get(rotated).status_code == 200


def test_rss_pull_delivery_is_idempotent_owned_and_tracks_downloaded_availability(library, monkeypatch, tmp_path):
    from backend.api.endpoints.vodloft import integrations
    from backend.db.models.vodloft import IntegrationFeedDelivery, IntegrationFeedItem, FeedSubscription
    client, sessions, _, gateway, _ = library
    with sessions() as session:
        session.connection().exec_driver_sql('PRAGMA foreign_keys=ON')
    snapshot = MediaSnapshot(kind='collection', reference=ref('example.com', 'abs-feed'), title='Podcast',
        entries=[EntrySnapshot(reference=ref('example.com', 'abs-episode'), title='Episode', position=1)])
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **k: snapshot)
    collection = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump(mode='json')}).json()
    item_id = client.get(f"/api/vodloft/library/{collection['id']}").json()['entries'][0]['id']
    profile = client.post(f"/api/vodloft/library/{collection['id']}/stream-profiles", json={'name': 'Podcast'}).json()
    target = client.post('/api/vodloft/integrations', json={'kind': 'audiobookshelf', 'name': 'ABS',
        'base_url': 'http://abs:13378', 'library_id': 'lib', 'local_prefix': str(tmp_path),
        'server_prefix': '/podcasts', 'api_key': 'delivery-secret'}).json()
    original = tmp_path / 'vodloft' / 'episode.mp3'; original.parent.mkdir(); original.write_bytes(b'immutable audio')
    with sessions() as session:
        session.add(Artifact(item_id=item_id, path=str(original), size=original.stat().st_size)); session.commit()
    remote = {}; calls = []
    def request(target, method, path, payload=None, **kw):
        calls.append((method, path, payload))
        if '/items?limit=' in path:
            return json.dumps({'results': [remote] if remote else [], 'total': int(bool(remote))}).encode()
        if method == 'POST' and path == '/api/podcasts':
            assert not remote, 'Retry must not create a second podcast'
            assert payload['media']['autoDownloadEpisodes'] and payload['folderId'] == 'folder'
            remote.update({'id': 'podcast', 'libraryId': 'lib', 'mediaType': 'podcast', 'path': payload['path'],
                'media': {'metadata': payload['media']['metadata'], 'episodes': []}})
            return json.dumps(remote).encode()
        if path.startswith('/api/items/'):
            return json.dumps(remote).encode()
        if '/checknew?' in path: return b'{}'
        raise AssertionError(path)
    monkeypatch.setattr(integrations, '_request', request)
    response = client.post('/api/vodloft/integrations/rss', json={'target_id': target['id'],
        'stream_profile_id': profile['id'], 'folder_id': 'folder', 'server_path': '/podcasts/Podcast',
        'vodloft_url': 'http://testserver'})
    assert response.status_code == 201, response.text
    delivery_id = response.json()['id']
    feed_url = remote['media']['metadata']['feedUrl']
    feed = client.get(feed_url)
    assert feed.status_code == 200, feed.text
    enclosure = ElementTree.fromstring(feed.content).find('channel/item/enclosure').attrib['url']
    remote['media']['episodes'] = [{'id': 'episode', 'enclosure': {'url': enclosure}, 'audioFile': {'path': '/podcasts/Podcast/episode.mp3'}}]
    integrations.reconcile_feed_delivery(delivery_id)
    assert client.get(f'/api/vodloft/library/{item_id}/integrations').json()[0]['state'] == 'available'
    original.unlink()
    assert client.get(enclosure).content == b'immutable audio'
    assert sum(path == '/api/podcasts' and method == 'POST' for method, path, _ in calls) == 1
    with sessions() as session:
        assert session.scalar(select(IntegrationFeedDelivery)).state == 'subscribed'
        assert session.scalar(select(IntegrationFeedItem)).available
    remote['media']['metadata']['feedUrl'] = 'https://unrelated.example/feed.xml'
    integrations.reconcile_feed_delivery(delivery_id)
    assert client.get('/api/vodloft/integrations/rss').json()[0]['state'] == 'failed'
    assert client.delete(f'/api/vodloft/integrations/rss/{delivery_id}').status_code == 204
    assert client.get(feed_url).status_code == 404 and client.get(enclosure).status_code == 404
    assert not any(method == 'DELETE' for method, _, _ in calls)
    with sessions() as session:
        assert session.scalar(select(FeedSubscription)) is None
        assert session.scalar(select(IntegrationFeedDelivery)) is None
        assert session.scalar(select(IntegrationFeedItem)) is None


def test_abs_progress_uses_each_local_users_verified_token(library, monkeypatch):
    from backend.api.endpoints.vodloft import integrations
    from backend.security import permissions
    from backend.db.models.vodloft import (Domain, LocalUser, CollectionStreamProfile, FeedSubscription,
        IntegrationFeedDelivery, IntegrationFeedItem, PlaybackProgress)
    client, sessions, _, _, _ = library
    target = client.post('/api/vodloft/integrations', json={'kind': 'audiobookshelf', 'name': 'ABS',
        'base_url': 'http://abs:13378', 'library_id': 'lib', 'local_prefix': '/downloads',
        'server_prefix': '/podcasts', 'api_key': 'administrator-token'}).json()
    with sessions() as session:
        domain = Domain(hostname='example.com', display_name='Example'); session.add(domain); session.flush()
        collection = MediaItem(domain_id=domain.id, kind='collection', title='Podcast')
        item = MediaItem(domain_id=domain.id, kind='video', title='Episode')
        session.add_all([collection, item]); session.flush(); item_id = item.id
        profile = CollectionStreamProfile(collection_id=collection.id, name='Podcast'); session.add(profile); session.flush()
        subscription = FeedSubscription(collection_id=collection.id, stream_profile_id=profile.id,
            user_key='integration:1', token='private-feed', integration_target_id=target['id'])
        session.add(subscription); session.flush()
        delivery = IntegrationFeedDelivery(target_id=target['id'], subscription_id=subscription.id,
            folder_id='folder', server_path='/podcasts/Podcast', feed_url='https://vodloft/feeds', state='subscribed', remote_id='remote-podcast')
        session.add(delivery); session.flush()
        row = IntegrationFeedItem(delivery_id=delivery.id, item_id=item.id, remote_episode_id='episode', available=True)
        session.add(row)
        for key in ['alice', 'bob']:
            session.add(LocalUser(key=key, username=key, password_hash='unused', role='member', target_ids=[target['id']], enabled=True))
        session.commit(); mapping_id = row.id
    actor = permissions.Principal(key='alice', role='member', target_ids=[target['id']])
    monkeypatch.setattr(permissions, 'principal', lambda request: actor)
    monkeypatch.setattr(integrations, 'principal', lambda request: actor)
    seen = []
    def request(target, method, path, payload=None, *, token_override=None):
        assert token_override != 'administrator-token'
        seen.append(token_override)
        return json.dumps({'id': token_override} if path == '/api/me' else {
            'currentTime': 80 if token_override == 'alice-token' else 20, 'isFinished': False}).encode()
    monkeypatch.setattr(integrations, '_request', request)
    for key in ['alice', 'bob']:
        actor = permissions.Principal(key=key, role='member', target_ids=[target['id']])
        wrong = client.put(f"/api/vodloft/integrations/{target['id']}/users", json={
            'user_key': key, 'remote_user_id': 'different-user', 'api_key': key + '-token'})
        assert wrong.status_code == 422
        mapped = client.put(f"/api/vodloft/integrations/{target['id']}/users", json={
            'user_key': key, 'remote_user_id': key + '-token', 'api_key': key + '-token'})
        assert mapped.status_code == 200, mapped.text
        response = client.post(f'/api/vodloft/integrations/rss-items/{mapping_id}/progress/pull')
        assert response.status_code == 200, response.text
    with sessions() as session:
        assert {row.user_key: row.seconds for row in session.scalars(select(PlaybackProgress)).all()} == {'alice': 80, 'bob': 20}
    actor = permissions.Principal(key='bob', role='member')
    assert client.post(f'/api/vodloft/integrations/rss-items/{mapping_id}/progress/pull').status_code == 404


def test_generic_artwork_selects_role_reencodes_and_caches(library, monkeypatch):
    import base64
    import io
    from PIL import Image
    from backend.services import vodloft_artwork
    from source_contracts import ArtworkCandidate
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(vodloft_artwork, 'get_session', sessions)
    monkeypatch.setattr(vodloft_artwork, 'validate_public_url', lambda url: url)
    snapshot = MediaSnapshot(kind='movie', reference=ref('example.com', 'poster'), title='Movie', artwork=[
        ArtworkCandidate(url='https://images.example.com/landscape.png', role='landscape', width=320, height=180),
        ArtworkCandidate(url='https://images.example.com/portrait.png', role='portrait', width=120, height=180)])
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **k: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump(mode='json')}).json()['id']
    calls = []
    def fetch(self, source, operation, **kwargs):
        calls.append(kwargs['url']); assert not kwargs['headers']
        buffer = io.BytesIO(); Image.new('RGB', (120, 180), 'blue').save(buffer, 'PNG')
        return {'data': base64.b64encode(buffer.getvalue()).decode()}
    monkeypatch.setattr(gateway.SourceGateway, 'call', fetch)
    response = client.get(f'/api/vodloft/library/{item_id}/artwork?shape=portrait')
    assert response.status_code == 200 and response.headers['content-type'] == 'image/jpeg'
    assert calls == ['https://images.example.com/portrait.png']
    assert Image.open(io.BytesIO(response.content)).format == 'JPEG'
    assert client.get(f'/api/vodloft/library/{item_id}/artwork?shape=portrait').content == response.content
    assert len(calls) == 1
    assert client.get(f'/api/vodloft/library/{item_id}/artwork?shape=svg').status_code == 422


def test_source_processing_event_reports_actual_job_stage(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind='video', reference=ref('example.com', 'processing'), title='Processing')
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **k: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump(mode='json')}).json()['id']
    profile_id = client.post('/api/vodloft/profiles', json={'name': 'Processing', 'domain': 'example.com'}).json()['id']
    job_id, _, _ = router.queue_download(item_id, profile_id)
    def download(self, source_id, url, staging, **kwargs):
        kwargs['on_progress'](60); kwargs['on_stage']('downloading')
        assert client.get(f'/api/vodloft/jobs/{job_id}').json()['progress'] > 35
        kwargs['on_stage']('processing')
        assert client.get(f'/api/vodloft/jobs/{job_id}').json()['state'] == 'processing'
        kwargs['on_stage']('downloading')
        assert client.get(f'/api/vodloft/jobs/{job_id}').json()['state'] == 'processing'
        path = Path(staging) / 'media.mp4'; path.write_bytes(b'media')
        return DownloadResult(filename=path.name, size=5)
    monkeypatch.setattr(gateway.SourceGateway, 'download', download)
    router._run_download(job_id)
    from task_manager.scheduler.db import TaskOperation
    with sessions() as session:
        operation = session.get(TaskOperation, session.get(AcquisitionJob, job_id).operation_id)
        assert [stage['stage'] for stage in operation.context['stages']] == [
            'queued', 'resolving', 'downloading', 'processing', 'verifying', 'finalizing', 'available']


def test_group_role_filters_future_groups_and_feed_limits_preserve_enclosures(library, monkeypatch, tmp_path):
    from datetime import datetime, timezone
    client, sessions, router, gateway, automation = library
    snapshots = [EntrySnapshot(reference=ref('example.com', str(i)), title=f'Episode {i}', position=i,
        group=group, role=role, published_at=datetime(2026, 9, i, tzinfo=timezone.utc))
        for i, group, role in [(1, 'Group 1', 'episode'), (2, 'Group 1', 'trailer'), (3, 'Group 2', 'episode')]]
    collection = MediaSnapshot(kind='collection', reference=ref('example.com', 'groups'), title='Collection', entries=snapshots)
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *a, **kw: collection)
    collection_id = client.post('/api/vodloft/import', json={'snapshot': collection.model_dump(mode='json')}).json()['id']
    profile_id = client.post('/api/vodloft/profiles', json={'name': 'Audio', 'domain': 'example.com', 'preferred_format': 'format_audio_only'}).json()['id']
    policy = client.post(f'/api/vodloft/library/{collection_id}/download-profiles', json={'name': 'Selected',
        'local_profile_ids': [profile_id], 'backfill': 'all', 'selected_groups': ['Group 1'], 'member_roles': ['episode'],
        'include_future_groups': True}).json()
    entries = client.get(f'/api/vodloft/library/{collection_id}').json()['entries']
    with sessions() as session:
        session.add(CollectionEntry(collection_id=collection_id, item_id=entries[2]['id'], position=4, group='Group 3', role='episode'))
        root = tmp_path / 'vodloft'; root.mkdir()
        for item in entries:
            path = root / f"{item['id']}.mp3"; path.write_bytes(item['title'].encode())
            session.add(Artifact(item_id=item['id'], path=str(path), size=path.stat().st_size))
        session.commit()
    decision = automation.schedule_profile(policy['id'], dispatch=False)
    from backend.db.models.vodloft import MediaDemand
    with sessions() as session:
        requested = {demand.item_id for demand in session.scalars(select(MediaDemand).where(
            MediaDemand.owner_kind == 'policy', MediaDemand.owner_id == policy['id'])).all()}
    assert requested == {entries[0]['id'], entries[2]['id']}
    assert len(decision['skipped']) == 2
    stream = client.post(f'/api/vodloft/library/{collection_id}/stream-profiles', json={'name': 'Feed',
        'format': 'audio', 'member_roles': ['episode'], 'max_items': 1, 'feed_title': 'Selected podcast'}).json()
    url = client.post(f"/api/vodloft/stream-profiles/{stream['id']}/feed").json()['url']
    channel = ElementTree.fromstring(client.get(url).content).find('channel')
    assert channel.find('title').text == 'Selected podcast' and len(channel.findall('item')) == 1
    enclosure = channel.find('item/enclosure').attrib['url']; guid = channel.find('item/guid').text
    assert channel.find('item/title').text == 'Episode 3'
    assert client.put(f"/api/vodloft/stream-profiles/{stream['id']}", json={**stream, 'member_roles': ['trailer']}).status_code == 200
    channel = ElementTree.fromstring(client.get(url).content).find('channel')
    assert channel.find('item/title').text == 'Episode 2' and channel.find('item/guid').text != guid
    assert client.get(enclosure).content == b'Episode 3'


def test_feed_preparation_acquires_portable_files_and_preserves_shared_demand(library, monkeypatch):
    from backend.api.endpoints.vodloft import feeds
    from backend.db.models.vodloft import MediaDemand
    client, sessions, router, gateway, _ = library
    collection = MediaSnapshot(kind='collection', reference=ref('example.com', 'podcast'), title='Podcast',
        entries=[EntrySnapshot(reference=ref('example.com', 'episode'), title='Episode', position=1)])
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *args, **kwargs: collection)
    collection_id = client.post('/api/vodloft/import', json={'snapshot': collection.model_dump()}).json()['id']
    profile_id = client.post('/api/vodloft/profiles', json={'name': 'Podcast audio', 'domain': 'example.com',
        'preferred_format': 'format_audio_only', 'representation': {'container': 'mp3'}}).json()['id']
    profile = client.post(f'/api/vodloft/library/{collection_id}/stream-profiles', json={
        'name': 'Prepared feed', 'local_only': False, 'local_profile_ids': [profile_id]})
    assert profile.status_code == 201, profile.text
    stream_id = profile.json()['id']
    assert profile.json()['source_reference_id'] is not None
    feed_url = client.post(f'/api/vodloft/stream-profiles/{stream_id}/feed').json()['url']
    assert ElementTree.fromstring(client.get(feed_url).content).find('channel/item') is None
    prepared = feeds.prepare_stream_profile(stream_id, dispatch=False)
    assert prepared['considered'] == 1 and len(prepared['queued_job_ids']) == 1
    assert feeds.prepare_stream_profile(stream_id, dispatch=False)['queued_job_ids'] == []
    def download(self, source_id, url, staging, **kwargs):
        output = Path(staging) / 'portable.mp3'
        output.write_bytes(b'portable feed audio')
        return DownloadResult(filename=output.name, size=output.stat().st_size)
    monkeypatch.setattr(gateway.SourceGateway, 'download', download)
    router._run_download(prepared['queued_job_ids'][0])
    enclosure = ElementTree.fromstring(client.get(feed_url).content).find('channel/item/enclosure').attrib['url']
    assert client.get(enclosure).content == b'portable feed audio'
    with sessions() as session:
        artifact = session.scalar(select(Artifact)); item_id, path = artifact.item_id, artifact.path
        assert session.scalar(select(MediaDemand)).owner_kind == 'stream'
    assert router.queue_download(item_id, profile_id)[1] == 'available'
    assert client.delete(f'/api/vodloft/stream-profiles/{stream_id}').status_code == 204
    assert client.get(enclosure).status_code == 404
    with sessions() as session:
        assert {d.owner_kind for d in session.scalars(select(MediaDemand)).all()} == {'direct'}
        assert session.scalar(select(Artifact)).path == path and Path(path).is_file()


def test_feed_scheduler_reuses_failed_job_and_preserves_retry_budget(library, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from backend.api.endpoints.vodloft import feeds
    client, sessions, router, gateway, _ = library
    collection = MediaSnapshot(kind='collection', reference=ref('example.com', 'retry-feed'), title='Retry feed',
        entries=[EntrySnapshot(reference=ref('example.com', 'retry-episode'), title='Episode', position=1)])
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *args, **kwargs: collection)
    collection_id = client.post('/api/vodloft/import', json={'snapshot': collection.model_dump()}).json()['id']
    local_id = client.post('/api/vodloft/profiles', json={'name': 'Retry audio', 'domain': 'example.com',
        'preferred_format': 'format_audio_only'}).json()['id']
    stream_id = client.post(f'/api/vodloft/library/{collection_id}/stream-profiles', json={
        'name': 'Retry', 'local_only': False, 'local_profile_ids': [local_id]}).json()['id']
    monkeypatch.setattr(get_settings().download_settings, 'max_download_attempts', 2)
    def unavailable(*args, **kwargs):
        raise RuntimeError('temporary provider outage')
    monkeypatch.setattr(gateway.SourceGateway, 'download', unavailable)
    job_id = feeds.prepare_stream_profile(stream_id, dispatch=False)['queued_job_ids'][0]
    router._run_download(job_id)
    assert feeds.prepare_stream_profile(stream_id, dispatch=False)['queued_job_ids'] == []
    dispatched = []
    thread_factory = router.threading.Thread
    def record_dispatch(**kwargs):
        return SimpleNamespace(start=lambda: dispatched.append(kwargs['args'][0]))
    monkeypatch.setattr(router.threading, 'Thread', record_dispatch)
    router.retry_due_acquisition_jobs()
    assert dispatched == []
    with sessions() as session:
        job = session.get(AcquisitionJob, job_id)
        assert job.attempts == 1
        job.updated_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()
    router.retry_due_acquisition_jobs()
    assert dispatched == [job_id]
    monkeypatch.setattr(router.threading, 'Thread', thread_factory)
    router._run_download(job_id)
    monkeypatch.setattr(router.threading, 'Thread', record_dispatch)
    assert feeds.prepare_stream_profile(stream_id, dispatch=False)['queued_job_ids'] == []
    with sessions() as session:
        jobs = session.scalars(select(AcquisitionJob)).all()
        assert len(jobs) == 1 and jobs[0].attempts == 2 and jobs[0].state == 'failed'
        jobs[0].updated_at = datetime.now(timezone.utc) - timedelta(days=1); session.commit()
    router.retry_due_acquisition_jobs()
    assert dispatched == [job_id]


@pytest.mark.parametrize('has_credentials', [False, True])
def test_legacy_aliases_reuse_modern_media_without_changing_existing_account_scope(library, monkeypatch, has_credentials):
    import uuid
    from backend.db.models import Show
    from backend.db.models.vodloft import Domain, LegacyMediaLink, SourceConnection
    from dailywire_authorisation.storage import TokenStore
    client, sessions, _, _, _ = library
    legacy = importlib.import_module('backend.db.background_migrations.versions.8e5a2c9f41d0_vodloft_legacy_library')
    conversion = importlib.import_module('backend.db.background_migrations.versions.a03f7e9bc261_vodloft_automation_conversion')
    monkeypatch.setattr(legacy, 'get_session', sessions)
    monkeypatch.setattr(conversion, 'get_session', sessions)
    with sessions() as session:
        domain = Domain(hostname='dailywire.com', display_name='Daily Wire')
        session.add(domain); session.flush()
        item = MediaItem(domain_id=domain.id, kind='collection', title='Current metadata', user_title='My title')
        session.add(item); session.flush()
        url = 'https://www.dailywire.com/show/preexisting'
        reference = SourceReference(item_id=item.id, source_id='dailywire', domain_id=domain.id,
            namespace='show', upstream_id=str(uuid.uuid5(uuid.NAMESPACE_URL, url)), url=url, connection_key=0)
        show = Show(uuid='legacy-show', slug='preexisting', title='Legacy title',
            sharing_url='https://www.dailywire.com/shows/preexisting', membership_level='FREE',
            type='series', episode_identifier='seasonal', author_name='Host', author_slug='host')
        session.add_all([reference, show]); session.commit()
        item_id, public_id = item.id, reference.id
    credentials = SimpleNamespace(access_token='legacy-token', refresh_token='legacy-refresh', expires_at=4102444800)
    monkeypatch.setattr(TokenStore, 'load', lambda *args: credentials if has_credentials else None)
    saved = []
    monkeypatch.setattr(conversion.secret_store, 'save', lambda value: saved.append(json.loads(value)) or 'encrypted-fixture')
    context = SimpleNamespace(raise_if_cancelled=lambda: None, update_progress=lambda *args: None)
    legacy._migrate(context)
    with sessions() as session:
        alias = session.scalar(select(SourceReference).where(SourceReference.upstream_id == 'preexisting'))
        artifact = Artifact(item_id=item_id, source_reference_id=alias.id, path='/unchanged/legacy.mp4', size=10)
        session.add(artifact); session.commit()
    for _ in range(2):
        conversion._convert(context); legacy._migrate(context)
    with sessions() as session:
        assert len(session.scalars(select(MediaItem)).all()) == 1
        assert session.scalar(select(LegacyMediaLink)).item_id == item_id
        assert session.get(MediaItem, item_id).user_title == 'My title'
        assert session.get(SourceReference, public_id).connection_id is None
        references = session.scalars(select(SourceReference)).all()
        assert len(references) == (2 if has_credentials else 1)
        artifact = session.scalar(select(Artifact))
        if has_credentials:
            imported = session.scalar(select(SourceConnection))
            assert imported.authentication_reference == 'encrypted-fixture'
            assert session.get(SourceReference, artifact.source_reference_id).connection_id == imported.id
            assert len(saved) == 1 and saved[0]['private_state']['refresh_token'] == 'legacy-refresh'
        else:
            assert artifact.source_reference_id == public_id
        assert artifact.path == '/unchanged/legacy.mp4'


def test_public_library_envelope_preserves_an_intentionally_blank_description(library, monkeypatch):
    client, sessions, router, gateway, _ = library
    snapshot = MediaSnapshot(kind='video', reference=ref('example.com', 'blank-description'),
        title='Source title', description='Source description',
        chapters=[{'title': 'Opening', 'start': 0}], tracks=[{'kind': 'audio', 'language': 'en'}])
    monkeypatch.setattr(gateway.SourceGateway, 'resolve', lambda *args, **kwargs: snapshot)
    item_id = client.post('/api/vodloft/import', json={'snapshot': snapshot.model_dump()}).json()['id']
    with sessions() as session:
        item = session.get(MediaItem, item_id)
        item.user_title, item.user_description = 'My title', ''
        session.commit()
    detail = client.get(f'/api/vodloft/library/{item_id}').json()
    assert detail['title'] == 'My title' and detail['description'] == ''
    assert detail['chapters'][0]['title'] == 'Opening' and detail['tracks'][0]['language'] == 'en'
    assert detail['references'][0]['source_id'] == 'fixture'
    assert 'url' not in detail['references'][0]
    client.put(f'/api/vodloft/library/{item_id}/progress', json={'seconds': 12})
    continued = client.get('/api/vodloft/home').json()['continue'][0]
    assert continued['id'] == item_id and continued['seconds'] == 12


def test_source_publisher_catalogue_is_accepted_by_the_update_verifier_and_detects_changed_wheels(tmp_path, monkeypatch):
    import hashlib
    import runpy
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from backend.source_manager import release_catalog
    publisher = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tools' / 'publish_source_catalogue.py'))
    bundle = tmp_path / 'bundle'; bundle.mkdir()
    filename = 'fixture-1.0.0-py3-none-any.whl'
    wheel = bundle / filename; wheel.write_bytes(b'fixture release')
    manifest = {'source_id': 'fixture', 'version': '1.0.0', 'adapter_version': '1.0.0', 'channel': 'stable',
        'protocol_version': 1, 'metadata_schema_version': 1, 'packages': {'fixture': '1.0.0'},
        'wheels': {filename: hashlib.sha256(wheel.read_bytes()).hexdigest()}}
    (bundle / 'release.json').write_text(json.dumps(manifest))
    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / 'publisher.pem'
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    catalog = tmp_path / 'catalogue.json'
    result = publisher['sign_bundle'](bundle, 'https://releases.example.com/fixture/1.0.0', key_file, catalog)
    monkeypatch.setattr(release_catalog, '_fetch_https', lambda *args: catalog.read_bytes())
    releases = release_catalog._verified_releases('fixture', {'url': 'https://releases.example.com/index.json',
        'public_key': result['public_key']})
    assert releases[0]['packages']['fixture'] == '1.0.0' and releases[0]['metadata_schema_version'] == 1
    assert releases[0]['wheels'][filename]['url'].endswith(filename)
    wheel.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match='digest'):
        publisher['sign_bundle'](bundle, 'https://releases.example.com/fixture/1.0.0', key_file, catalog)


def test_shared_movie_extra_edits_keep_parents_roles_and_explicit_choices(library, monkeypatch):
    from backend.db.models.vodloft import MovieExtraParent
    client, sessions, _, gateway, _ = library
    snapshots = {}
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda self, source_id, url, **kw: snapshots[url])
    shared = ref("example.com", "shared-extra")
    standalone = MediaSnapshot(kind="video", reference=shared, title="Standalone clip")
    snapshots[shared.url] = standalone
    direct = client.post("/api/vodloft/import", json={"snapshot": standalone.model_dump(mode="json")})
    assert direct.status_code == 200 and direct.json()["kind"] == "video"
    movies = []
    for index, role in enumerate(("trailer", "interview"), start=1):
        snapshot = MediaSnapshot(kind="movie", reference=ref("example.com", f"movie-{index}"),
            title=f"Movie {index}", extras=[EntrySnapshot(reference=shared, title="Shared extra",
                kind="movie_extra", position=1, extra_type=role)])
        snapshots[snapshot.reference.url] = snapshot
        result = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")})
        assert result.status_code == 200, result.text
        movies.append((result.json()["id"], snapshot))
    first = client.get(f"/api/vodloft/library/{movies[0][0]}").json()
    second = client.get(f"/api/vodloft/library/{movies[1][0]}").json()
    extra_id = first["extras"][0]["id"]
    assert extra_id == direct.json()["id"] and first["extras"][0]["kind"] == "movie_extra"
    assert second["extras"][0]["id"] == extra_id
    assert first["extras"][0]["extra_type"] == "trailer"
    assert second["extras"][0]["extra_type"] == "interview"
    assert set(client.get(f"/api/vodloft/library/{extra_id}").json()["parent_ids"]) == {m[0] for m in movies}

    response = client.put(f"/api/vodloft/library/{extra_id}/metadata",
        json={"title": "Personal title", "parent_id": movies[0][0]})
    assert response.status_code == 200, response.text
    assert set(response.json()["parent_ids"]) == {m[0] for m in movies}
    with sessions() as session:
        assert len(session.scalars(select(MovieExtraParent).where(MovieExtraParent.extra_id == extra_id)).all()) == 2

    response = client.put(f"/api/vodloft/library/{extra_id}/metadata",
        json={"parent_ids": [movies[1][0]], "extra_type": "featurette"})
    assert response.status_code == 200, response.text
    assert response.json()["parent_ids"] == [movies[1][0]]
    # Source refresh cannot reattach a parent removed by the user or replace the chosen role.
    for _, snapshot in movies:
        response = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")})
        assert response.status_code == 200, response.text
    extra = client.get(f"/api/vodloft/library/{extra_id}").json()
    assert extra["title"] == "Personal title"
    assert extra["parent_ids"] == [movies[1][0]] and extra["extra_type"] == "featurette"
    assert client.get(f"/api/vodloft/library/{movies[0][0]}").json()["extras"] == []
    assert client.put(f"/api/vodloft/library/{extra_id}/metadata", json={"parent_ids": []}).status_code == 422
    assert client.put(f"/api/vodloft/library/{extra_id}/metadata", json={"parent_ids": [extra_id]}).status_code == 422
    assert client.put(f"/api/vodloft/library/{extra_id}/metadata", json={"kind": "video"}).status_code == 200
    response = client.post("/api/vodloft/import", json={"snapshot": movies[1][1].model_dump(mode="json")})
    assert response.status_code == 200
    assert client.get(f"/api/vodloft/library/{extra_id}").json()["kind"] == "video"
    assert client.get(f"/api/vodloft/library/{movies[1][0]}").json()["extras"] == []


def test_source_activation_validates_saved_private_authentication(library, monkeypatch):
    from backend import db
    from backend.db.models.vodloft import SourceConnection
    from backend.source_manager import runtime, secrets
    _, sessions, _, _, _ = library
    monkeypatch.setattr(db, "get_session", sessions)
    reference = secrets.save(json.dumps({"configuration": {"access_token": "private-value"}}))
    with sessions() as session:
        session.add(SourceConnection(source_id="fixture", name="Authenticated",
            settings={}, secret_references={}, authentication_reference=reference))
        session.commit()
    manifest = SourceManifest(source_id="fixture", display_name="Fixture", version="2", capabilities=set(),
        configuration_schema=[{"name": "access_token", "label": "Token", "kind": "secret", "required": True}])
    runtime._validate_saved_configuration(manifest)
    incompatible = manifest.model_copy(update={"configuration_schema": []})
    with pytest.raises(ValueError, match="review saved connections"):
        runtime._validate_saved_configuration(incompatible)


def test_upstream_session_stays_pinned_when_local_file_arrives(library, monkeypatch, tmp_path):
    import base64
    from backend.api.endpoints.vodloft import playback
    from backend.db.models.vodloft import PlaybackSession
    from source_contracts import StreamLease
    client, sessions, _, gateway, _ = library
    monkeypatch.setattr(playback, "get_session", sessions)
    monkeypatch.setattr(playback, "validate_public_url", lambda url: url)
    snapshot = MediaSnapshot(kind="video", reference=ref("example.com", "handoff"), title="Handoff")
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *a, **k: snapshot)
    item_id = client.post("/api/vodloft/import", json={"snapshot": snapshot.model_dump(mode="json")}).json()["id"]
    old_command = [sys.executable, "-m", "fixture_old.worker"]
    monkeypatch.setattr(gateway.SourceGateway, "__init__", lambda self, commands=None:
        setattr(self, "commands", commands or {"fixture": old_command}))
    monkeypatch.setattr(gateway.SourceGateway, "stream_lease", lambda *a, **k:
        StreamLease(transport="http", url="https://cdn.example.com/current.mp4", representation_id="upstream-1"))
    commands = []
    def fetch(self, source, operation, **options):
        commands.append(self.commands[source])
        return {"data": base64.b64encode(b"upstream bytes").decode(), "content_type": "video/mp4",
            "status": 200, "url": options["url"]}
    monkeypatch.setattr(gateway.SourceGateway, "call", fetch)
    upstream = client.post(f"/api/vodloft/library/{item_id}/watch").json()
    assert client.get(upstream["url"]).content == b"upstream bytes"
    local = tmp_path / "vodloft" / "arrived.mp4"
    local.parent.mkdir(exist_ok=True); local.write_bytes(b"local bytes")
    with sessions() as session:
        session.add(Artifact(item_id=item_id, path=str(local), size=local.stat().st_size))
        session.commit()
    # New sessions prefer local; the existing session keeps upstream bytes and its original worker.
    fresh = client.post(f"/api/vodloft/library/{item_id}/watch").json()
    assert fresh["transport"] == "file" and client.get(fresh["url"]).content == b"local bytes"
    assert client.get(upstream["url"]).content == b"upstream bytes"
    assert commands == [old_command, old_command]
    with sessions() as session:
        assert sorted(s.transport for s in session.scalars(select(PlaybackSession)).all()) == ["file", "http"]


def test_upstream_disappearance_and_server_outage_preserve_local_acquisition(library, monkeypatch, tmp_path):
    import threading
    from backend.api.endpoints.vodloft import integrations
    from backend.db.models.vodloft import MediaServerExport, MediaServerTarget
    client, sessions, router, gateway, _ = library
    item_ref = ref("example.com", "offline-safe")
    collection = MediaSnapshot(kind="collection", reference=ref("example.com", "vanished-list"), title="List",
        entries=[EntrySnapshot(reference=item_ref, title="Local survives", position=1)])
    monkeypatch.setattr(gateway.SourceGateway, "resolve", lambda *a, **k: collection)
    collection_id = client.post("/api/vodloft/import", json={"snapshot": collection.model_dump(mode="json")}).json()["id"]
    item_id = client.get(f"/api/vodloft/library/{collection_id}").json()["entries"][0]["id"]
    with sessions() as session:
        target = MediaServerTarget(kind="jellyfin", name="Unavailable server", base_url="http://server.example",
            library_id="1", local_prefix=str(tmp_path), server_prefix="/media", secret_ciphertext="unused", enabled=True)
        session.add(target); session.commit(); target_id = target.id
    profile = client.post("/api/vodloft/profiles", json={"name": "Outage safe", "domain": "example.com",
        "delivery_target_ids": [target_id]})
    assert profile.status_code == 201, profile.text
    def download(self, source_id, url, staging, **options):
        file = Path(staging) / "media.mp4"; file.write_bytes(b"local survives")
        return DownloadResult(filename=file.name, size=file.stat().st_size)
    monkeypatch.setattr(gateway.SourceGateway, "download", download)
    monkeypatch.setattr(integrations, "discover", lambda target: (_ for _ in ()).throw(OSError("server offline")))
    original_thread = threading.Thread
    class ImmediateExport:
        def __init__(self, target, args, **kw): self.target, self.args = target, args
        def start(self): self.target(*self.args)
    monkeypatch.setattr(threading, "Thread", lambda *a, **kw:
        ImmediateExport(*a, **kw) if kw.get("name", "").startswith("vodloft-export-") else original_thread(*a, **kw))
    job_id, _, _ = router.queue_download(item_id, profile.json()["id"])
    router._run_download(job_id)
    assert client.get(f"/api/vodloft/jobs/{job_id}").json()["state"] == "available"
    with sessions() as session:
        export = session.scalar(select(MediaServerExport))
        assert export.state == "failed" and export.attempts == 1
    assert client.get(f"/api/vodloft/library/{item_id}/play").content == b"local survives"
    collection = collection.model_copy(update={"entries": [], "enumeration_complete": True})
    assert client.post("/api/vodloft/import", json={"snapshot": collection.model_dump(mode="json")}).status_code == 200
    assert client.get(f"/api/vodloft/library/{item_id}/play").content == b"local survives"
    assert client.get(f"/api/vodloft/library/{item_id}").json()["downloaded"]
