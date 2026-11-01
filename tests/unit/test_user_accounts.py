"""User accounts: signing in, sessions, the first and the last administrator."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.security.passwords import derive_admin_password_client_value, hash_password_scrypt


def pw(password: str) -> str:
    """What the browser sends for a password."""
    return derive_admin_password_client_value(password)


DOWNLOADER = {"templateKey": "downloader", "levels": {"quick_downloads": "view"}}


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.db import core
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)
    from backend.db.models import Settings

    path = tmp_path / "vodloft-users.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(core, "_engine", engine)
    monkeypatch.setattr(core, "_SessionLocal", factory)
    monkeypatch.setattr(core, "_db_path", path)
    Base.metadata.create_all(engine)
    with factory() as session:
        session.add(Settings(onboarding_completed=True))
        session.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def environment_password(monkeypatch: pytest.MonkeyPatch):
    from config import get_settings

    monkeypatch.setattr(get_settings().admin_auth, "password_hash", hash_password_scrypt(pw("environment-pw")))
    return "environment-pw"


@pytest.fixture
def app(database):
    from backend.app import create_app

    return create_app()


def client(app) -> TestClient:
    # No ``with``: the app's lifespan would start the scheduler.
    return TestClient(app)


def sign_in(c: TestClient, password: str, username: str | None = None):
    body = {"passwordHash": pw(password)}
    if username is not None:
        body["username"] = username
    return c.post("/api/auth/login", json=body)


def turn_accounts_on(c: TestClient, username: str = "samuel", password: str = "admin-password"):
    return c.put("/api/users/settings", json={
        "enabled": True,
        "firstAdministrator": {"username": username, "passwordHash": pw(password)},
    })


def test_without_accounts_or_password_everything_is_open(app):
    c = client(app)
    me = c.get("/api/auth/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["accountsEnabled"] is False
    assert body["user"] is None
    assert body["administrator"] is True
    assert c.get("/api/config/public").json()["userAccounts"] == {"enabled": False}


def test_without_accounts_the_environment_password_signs_in(app, environment_password):
    c = client(app)
    assert c.get("/api/auth/me").status_code == 401
    assert sign_in(c, "wrong-password").status_code == 400
    assert sign_in(c, environment_password).status_code == 204
    assert c.get("/api/auth/me").json()["administrator"] is True


def test_turning_accounts_on_creates_and_signs_in_the_first_administrator(app, environment_password):
    c = client(app)
    sign_in(c, environment_password)

    refused = c.put("/api/users/settings", json={"enabled": True})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "firstAdministrator"]

    response = turn_accounts_on(c)
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True

    me = c.get("/api/auth/me").json()
    assert me["accountsEnabled"] is True
    assert me["user"]["username"] == "samuel"
    assert me["user"]["mustChangePassword"] is False
    assert me["administrator"] is True

    # The environment password alone no longer signs in while an administrator can.
    other = client(app)
    refused = sign_in(other, environment_password)
    assert refused.status_code == 400
    assert refused.json()["detail"][0]["loc"] == ["body", "username"]
    assert sign_in(other, "admin-password", "SAMUEL").status_code == 204


def test_a_new_user_must_choose_a_password_and_only_gets_their_access(app):
    admin = client(app)
    turn_accounts_on(admin)
    created = admin.post("/api/users", json={"username": "tim", "passwordHash": pw("first-pw"), "access": DOWNLOADER})
    assert created.status_code == 201, created.text
    assert created.json()["createdBy"] == "samuel"
    assert created.json()["levels"]["quick_downloads"] == "view"
    assert created.json()["levels"]["library"] == "none"

    tim = client(app)
    assert sign_in(tim, "first-pw", "tim").status_code == 204
    assert tim.get("/api/auth/me").json()["user"]["mustChangePassword"] is True
    blocked = tim.get("/api/users")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Choose a new password first."

    wrong = tim.post("/api/auth/password", json={"currentPasswordHash": pw("nope"), "newPasswordHash": pw("tims-own-pw")})
    assert wrong.status_code == 400
    changed = tim.post("/api/auth/password", json={"currentPasswordHash": pw("first-pw"), "newPasswordHash": pw("tims-own-pw")})
    assert changed.status_code == 204, changed.text
    assert tim.get("/api/auth/me").json()["user"]["mustChangePassword"] is False

    not_allowed = tim.get("/api/users")
    assert not_allowed.status_code == 403
    assert "access" in not_allowed.json()["detail"]


def test_disabling_a_user_ends_their_open_session(app):
    admin = client(app)
    turn_accounts_on(admin)
    user_id = admin.post("/api/users", json={"username": "tim", "passwordHash": pw("first-pw"), "access": DOWNLOADER}).json()["id"]

    tim = client(app)
    sign_in(tim, "first-pw", "tim")
    assert tim.get("/api/auth/me").status_code == 200

    assert admin.patch(f"/api/users/{user_id}", json={"enabled": False}).status_code == 200
    assert tim.get("/api/auth/me").status_code == 401
    assert sign_in(tim, "first-pw", "tim").status_code == 400

    admin.patch(f"/api/users/{user_id}", json={"enabled": True})
    assert sign_in(tim, "first-pw", "tim").status_code == 204
    admin.post(f"/api/users/{user_id}/sign-out")
    assert tim.get("/api/auth/me").status_code == 401


def test_a_reset_password_signs_the_user_out_and_must_be_changed(app):
    admin = client(app)
    turn_accounts_on(admin)
    user_id = admin.post("/api/users", json={"username": "tim", "passwordHash": pw("first-pw"), "access": DOWNLOADER}).json()["id"]
    tim = client(app)
    sign_in(tim, "first-pw", "tim")
    tim.post("/api/auth/password", json={"currentPasswordHash": pw("first-pw"), "newPasswordHash": pw("tims-own-pw")})

    assert admin.post(f"/api/users/{user_id}/password", json={"passwordHash": pw("reset-pw")}).status_code == 204
    assert tim.get("/api/auth/me").status_code == 401
    sign_in(tim, "reset-pw", "tim")
    assert tim.get("/api/auth/me").json()["user"]["mustChangePassword"] is True


def test_the_last_administrator_cannot_be_disabled_demoted_or_deleted(app):
    admin = client(app)
    turn_accounts_on(admin)
    me = admin.get("/api/auth/me").json()["user"]["id"]

    assert admin.patch(f"/api/users/{me}", json={"enabled": False}).status_code == 409
    assert admin.patch(f"/api/users/{me}", json={"access": DOWNLOADER}).status_code == 409
    assert admin.delete(f"/api/users/{me}").status_code == 409

    second = admin.post("/api/users", json={
        "username": "marieke", "passwordHash": pw("first-pw"),
        "access": {"templateKey": "administrator", "levels": {"users": "manage"}},
    })
    assert second.json()["administrator"] is True
    assert second.json()["levels"]["library"] == "manage"
    assert admin.patch(f"/api/users/{me}", json={"access": DOWNLOADER}).status_code == 200


def test_usernames_are_unique_regardless_of_case(app):
    admin = client(app)
    turn_accounts_on(admin)
    refused = admin.post("/api/users", json={"username": "Samuel", "passwordHash": pw("x-password"), "access": DOWNLOADER})
    assert refused.status_code == 409
    assert refused.json()["detail"][0]["loc"] == ["body", "username"]
    bad = admin.post("/api/users", json={"username": "no spaces", "passwordHash": pw("x-password"), "access": DOWNLOADER})
    assert bad.status_code == 422


def test_turning_accounts_off_ends_user_sessions(app, environment_password):
    admin = client(app)
    sign_in(admin, environment_password)
    turn_accounts_on(admin)
    assert admin.put("/api/users/settings", json={"enabled": False}).status_code == 200

    # The user session no longer counts; the shared password does.
    assert admin.get("/api/auth/me").status_code == 401
    assert sign_in(admin, environment_password).status_code == 204
    assert admin.get("/api/auth/me").json()["accountsEnabled"] is False


def test_the_environment_password_recovers_when_no_administrator_can_sign_in(app, database, environment_password):
    from backend.db.models import User

    admin = client(app)
    sign_in(admin, environment_password)
    turn_accounts_on(admin)
    with database() as session:
        session.query(User).update({User.is_enabled: False})
        session.commit()

    rescuer = client(app)
    assert sign_in(rescuer, environment_password).status_code == 204
    me = rescuer.get("/api/auth/me").json()
    assert me["recovery"] is True
    assert me["administrator"] is True

    user_id = rescuer.get("/api/users").json()[0]["id"]
    assert rescuer.patch(f"/api/users/{user_id}", json={"enabled": True}).status_code == 200
    # With an administrator back, the recovery session ends.
    assert rescuer.get("/api/auth/me").status_code == 401


def test_repeated_failures_slow_down_sign_in(app, environment_password, monkeypatch):
    from backend.security import login_throttle as module

    throttle = module.LoginThrottle(free_attempts_per_username=2, clock=lambda: 1000.0)
    monkeypatch.setattr("backend.api.endpoints.auth.router.login_throttle", throttle)
    c = client(app)
    assert sign_in(c, "wrong-1").status_code == 400
    assert sign_in(c, "wrong-2").status_code == 400
    assert sign_in(c, "wrong-3").status_code == 400
    slowed = sign_in(c, environment_password)
    assert slowed.status_code == 429
    assert slowed.headers["Retry-After"] == "2"


def test_throttle_waits_double_and_clear_on_success():
    from backend.security.login_throttle import LoginThrottle

    now = [0.0]
    throttle = LoginThrottle(free_attempts_per_username=1, free_attempts_per_address=100, clock=lambda: now[0])
    throttle.record_failure("Tim", "1.2.3.4")
    assert throttle.wait_seconds("tim", "5.6.7.8") == 0
    throttle.record_failure("tim", "1.2.3.4")
    assert throttle.wait_seconds("TIM", "5.6.7.8") == 2
    throttle.record_failure("tim", "1.2.3.4")
    assert throttle.wait_seconds("tim", None) == 3
    now[0] = 10.0
    assert throttle.wait_seconds("tim", None) == 0
    throttle.record_success("tim")
    throttle.record_failure("tim", None)
    assert throttle.wait_seconds("tim", None) == 0
