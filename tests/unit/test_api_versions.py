"""The API lives under /api/<version>/, and a client can ask which versions a server answers."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.security.passwords import derive_admin_password_client_value


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.app import create_app
    from backend.db import core
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)
    from backend.db.models import Settings

    path = tmp_path / "vodloft-api-versions.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", factory)
    monkeypatch.setattr(core, "_db_path", path)
    Base.metadata.create_all(engine)
    with factory() as session:
        session.add(Settings(onboarding_completed=True))
        session.commit()
    yield TestClient(create_app())
    engine.dispose()


def _sign_in(client: TestClient) -> None:
    client.put("/api/v1/users/settings", json={
        "enabled": True,
        "firstAdministrator": {"username": "admin", "passwordHash": derive_admin_password_client_value("admin-password")},
    })


def _walk(routes, prefix=""):
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes, prefix + route.include_context.prefix)
        elif isinstance(route, APIRoute):
            yield prefix + route.path


def test_every_api_route_is_under_a_version():
    from backend.app import create_app

    outside = [
        path for path in _walk(create_app().routes)
        if path.startswith("/api") and not path.startswith("/api/v1/")
    ]
    assert sorted(outside) == ["/api/health", "/api/versions", "/api/{path:path}"]


def test_anyone_can_ask_which_versions_the_server_answers(client):
    from config import get_settings

    response = client.get("/api/versions")

    assert response.status_code == 200
    assert response.json() == {"versions": ["v1"], "current": "v1", "appVersion": get_settings().app_version}


def test_a_path_outside_every_version_says_which_versions_there_are(client):
    """A client speaking a version this server does not gets told so, signed in or not, instead of 401."""
    for path in ["/api/collections", "/api/v0/collections", "/api/v2/pull"]:
        response = client.get(path)

        assert response.status_code == 404, path
        assert response.json()["versions"] == ["v1"]
        assert response.json()["current"] == "v1"
        assert "/api/v1/" in response.json()["detail"]


def test_an_unknown_path_within_a_version_is_only_not_found(client):
    _sign_in(client)

    response = client.get("/api/v1/no-such-thing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_routes_within_a_version_need_signing_in(client):
    _sign_in(client)
    signed_out = TestClient(client.app)

    assert signed_out.get("/api/v1/collections").status_code == 401
    assert signed_out.get("/api/v1/config/public").status_code == 200
    assert client.get("/api/v1/collections").status_code == 200


def test_the_old_unversioned_paths_are_gone(client):
    _sign_in(client)

    assert client.get("/api/collections").status_code == 404
    assert client.post("/api/auth/login", json={}).status_code == 404


def test_the_health_check_stays_outside_every_version(client):
    """Docker and uptime monitors keep one address for it, whatever the API's version is."""
    _sign_in(client)
    signed_out = TestClient(client.app)

    assert signed_out.get("/api/health").status_code in (200, 503)
    assert client.get("/api/v1/health").status_code == 404
