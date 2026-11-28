"""Every API route declares the access it needs, and the API enforces it.

Hiding something in the interface is only a convenience: these tests sign in
as each template and call the API directly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.security.passwords import derive_admin_password_client_value


def _walk(routes, prefix=""):
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes, prefix + route.include_context.prefix)
        elif isinstance(route, APIRoute):
            yield prefix + route.path, route


def _access_dependencies(dependant):
    from backend.security.deps import is_access_dependency

    for sub in dependant.dependencies:
        if sub.call is not None and is_access_dependency(sub.call):
            yield sub.call
        yield from _access_dependencies(sub)


def _api_routes():
    from backend.app import create_app

    return [(path, route) for path, route in _walk(create_app().routes) if path.startswith("/api/v1/")]


def test_every_api_route_declares_the_access_it_needs():
    from backend.app import PUBLIC_API_PATHS

    undeclared = [
        f"{','.join(sorted(route.methods))} {path}"
        for path, route in _api_routes()
        if path.removeprefix("/api/v1") not in PUBLIC_API_PATHS and not list(_access_dependencies(route.dependant))
    ]
    assert undeclared == [], "Add requires(...) or signed_in() to: " + ", ".join(undeclared)


def test_public_api_paths_are_only_signing_in_public_config_and_health():
    from backend.app import PUBLIC_API_PATHS

    assert PUBLIC_API_PATHS == {
        "/auth/status", "/auth/login", "/auth/logout", "/config/public", "/metrics",
    }


# Per template, through the real app ------------------------------------------


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app import create_app
    from backend.db import core
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)
    from backend.db.models import Settings

    path = tmp_path / "vodloft-access.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", factory)
    monkeypatch.setattr(core, "_db_path", path)
    Base.metadata.create_all(engine)
    with factory() as session:
        session.add(Settings(onboarding_completed=True))
        session.commit()
    yield create_app()
    engine.dispose()


def _client_for(app, template: str) -> TestClient:
    from backend.security.access import TEMPLATES

    admin = TestClient(app)
    admin.put("/api/v1/users/settings", json={
        "enabled": True,
        "firstAdministrator": {"username": "admin", "passwordHash": derive_admin_password_client_value("admin-password")},
    })
    if template == "administrator":
        return admin
    levels = {area.value: level.value for area, level in TEMPLATES[template].levels.items()}
    password = derive_admin_password_client_value(f"{template}-password")
    created = admin.post("/api/v1/users", json={
        "username": template, "passwordHash": password,
        "access": {"templateKey": template, "levels": levels},
    })
    assert created.status_code == 201, created.text
    user = TestClient(app)
    user.post("/api/v1/auth/login", json={"username": template, "passwordHash": password})
    user.post("/api/v1/auth/password", json={
        "currentPasswordHash": password,
        "newPasswordHash": derive_admin_password_client_value(f"{template}-own-password"),
    })
    return user


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "999999", path)


@pytest.mark.parametrize("template", ["library_manager", "viewer", "downloader"])
def test_routes_outside_a_template_answer_not_allowed(app, template):
    """Every route a template may not use answers 403, before it looks at the request at all."""
    from backend.app import PUBLIC_API_PATHS
    from backend.security.access import TEMPLATES, Access

    access = Access.for_user(
        user_id=0, username=template, levels=TEMPLATES[template].levels, source_limits=None,
        members_only=False, delete_files=TEMPLATES[template].delete_files,
        must_change_password=False, template_key=template, session_version=1,
    )
    client = _client_for(app, template)
    checked = 0
    for path, route in _walk(app.routes):
        if not path.startswith("/api/v1/") or path.removeprefix("/api/v1") in PUBLIC_API_PATHS:
            continue
        refused = False
        for dependency in _access_dependencies(route.dependant):
            try:
                dependency(_RequestWith(access))
            except Exception:
                refused = True
        if not refused:
            continue
        method = sorted(route.methods - {"HEAD"})[0]
        response = client.request(method, _concrete(path))
        assert response.status_code == 403, f"{method} {path} answered {response.status_code} for {template}"
        checked += 1
    assert checked > 0


class _RequestWith:
    def __init__(self, access):
        from types import SimpleNamespace

        self.state = SimpleNamespace(access=access)


@pytest.mark.parametrize(
    ("template", "allowed", "refused"),
    [
        (
            "downloader",
            ["/api/v1/quick-downloads", "/api/v1/quick-downloads/history", "/api/v1/quick-downloads/settings", "/api/v1/auth/me", "/api/v1/pull", "/api/v1/sources"],
            ["/api/v1/collections", "/api/v1/movies", "/api/v1/videos", "/api/v1/library/counts", "/api/v1/media-downloads", "/api/v1/settings",
             "/api/v1/download-profiles", "/api/v1/local-media-profiles", "/api/v1/rss-stream-profiles",
             "/api/v1/tasks/runs", "/api/v1/logs", "/api/v1/users", "/api/v1/sources/problems", "/api/v1/settings/library-defaults"],
        ),
        (
            "viewer",
            ["/api/v1/collections", "/api/v1/movies", "/api/v1/videos", "/api/v1/library/counts", "/api/v1/media-downloads", "/api/v1/rss-stream-profiles",
             "/api/v1/settings/library-defaults"],
            ["/api/v1/quick-downloads", "/api/v1/settings", "/api/v1/tasks/runs", "/api/v1/logs", "/api/v1/users",
             "/api/v1/download-profiles"],
        ),
        (
            "library_manager",
            ["/api/v1/collections", "/api/v1/media-downloads", "/api/v1/download-profiles", "/api/v1/local-media-profiles",
             "/api/v1/tasks/runs", "/api/v1/quick-downloads"],
            ["/api/v1/settings", "/api/v1/logs", "/api/v1/users", "/api/v1/sources/problems"],
        ),
        (
            "administrator",
            ["/api/v1/collections", "/api/v1/settings", "/api/v1/logs", "/api/v1/users", "/api/v1/tasks/runs", "/api/v1/quick-downloads"],
            [],
        ),
    ],
)
def test_templates_reach_what_they_should(app, template, allowed, refused):
    client = _client_for(app, template)
    for path in allowed:
        response = client.get(path)
        assert response.status_code not in (401, 403), f"{template} was refused {path}: {response.text}"
    for path in refused:
        assert client.get(path).status_code == 403, f"{template} reached {path}"


def test_deleting_files_is_its_own_switch(app):
    client = _client_for(app, "library_manager")
    # Library manager may manage downloads, but not delete files from disk.
    response = client.delete("/api/v1/media-downloads/999999/files")
    assert response.status_code == 403
    assert "delete downloaded files" in response.json()["detail"]
    assert client.delete("/api/v1/media-downloads/999999").status_code == 404


def test_users_only_see_their_own_operations(app):
    from backend.db.core import run_write_transaction
    from task_manager.scheduler.db import TaskOperation

    downloader = _client_for(app, "downloader")
    me = downloader.get("/api/v1/auth/me").json()["user"]["id"]
    def add(session):
        for op_id, requester in (("mine", me), ("theirs", None)):
            session.add(TaskOperation(
                id=op_id, kind="quick.download", source="ui", resource_type="quick_download",
                resource_id=None, title=op_id, status="queued", requested_by_user_id=requester,
            ))

    run_write_transaction(add)

    assert [operation["id"] for operation in downloader.get("/api/v1/operations").json()] == ["mine"]
    assert downloader.get("/api/v1/operations/theirs").status_code == 404
    assert [operation["id"] for operation in downloader.get("/api/v1/pull").json()["data"]["operations"]] == ["mine"]

    # Acknowledging marks only the operations this user may see.
    assert downloader.post("/api/v1/operations/seen", json={"operationIds": ["mine", "theirs"]}).status_code == 204

    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"username": "admin", "passwordHash": derive_admin_password_client_value("admin-password")})
    seen = {operation["id"]: operation["notificationSeenAt"] for operation in admin.get("/api/v1/operations").json()}
    assert seen.keys() == {"mine", "theirs"}
    assert seen["mine"] is not None
    assert seen["theirs"] is None


def test_operations_remember_who_asked(app):
    from backend.db.core import run_write_transaction
    from task_manager.scheduler.operations import create_operation
    from task_manager.scheduler.requester import current_requester

    token = current_requester.set(42)
    try:
        def add(session):
            from backend.db.models import User
            session.add(User(id=42, username="someone", password_hash="x"))
            operation = create_operation(
                session, kind="test", resource_type="none", resource_id=None, title="t", targets=(),
            )
            return operation.requested_by_user_id

        assert run_write_transaction(add) == 42
    finally:
        current_requester.reset(token)


def test_a_limited_user_is_refused_other_links_with_the_reason(app):
    admin = _client_for(app, "administrator")
    password = derive_admin_password_client_value("tim-password")
    from backend.security.access import TEMPLATES

    levels = {area.value: level.value for area, level in TEMPLATES["downloader"].levels.items()}
    created = admin.post("/api/v1/users", json={
        "username": "tim", "passwordHash": password,
        "access": {
            "templateKey": "downloader", "levels": levels,
            "sources": [{"sourceKey": "ytdlp", "domains": ["https://www.YouTube.com/", "youtu.be"]}],
        },
    })
    assert created.status_code == 201, created.text
    assert created.json()["sources"] == [{"sourceKey": "ytdlp", "domains": ["youtu.be", "youtube.com"]}]

    tim = TestClient(app)
    tim.post("/api/v1/auth/login", json={"username": "tim", "passwordHash": password})
    tim.post("/api/v1/auth/password", json={
        "currentPasswordHash": password, "newPasswordHash": derive_admin_password_client_value("tim-own-password"),
    })
    for path, body in (
        ("/api/v1/resolve", {"url": "https://vimeo.com/1"}),
        ("/api/v1/quick-downloads/options", {"url": "https://vimeo.com/1"}),
        ("/api/v1/quick-downloads", {"url": "https://vimeo.com/1", "choice": {}}),
    ):
        response = tim.post(path, json=body)
        assert response.status_code == 403, (path, response.text)
        assert "links on vimeo.com" in response.json()["detail"]
    assert "youtube.com" in tim.post("/api/v1/resolve", json={"url": "https://vimeo.com/1"}).json()["detail"]


def test_unknown_sources_cannot_be_given_to_a_user(app):
    admin = _client_for(app, "administrator")
    response = admin.post("/api/v1/users", json={
        "username": "tim", "passwordHash": derive_admin_password_client_value("tim-password"),
        "access": {"levels": {"quick_downloads": "view"}, "sources": [{"sourceKey": "nope", "domains": None}]},
    })
    assert response.status_code == 422
