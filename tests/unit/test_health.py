"""/api/health for Docker's health check, and the optional Prometheus metrics."""
from __future__ import annotations

from collections import namedtuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch, tmp_path):
    import backend.api.endpoints.collections.router  # noqa: F401  (loads every model first)
    from backend.api.endpoints.health import router as health_router_module
    from backend.db import Base
    from backend.services import health
    from config import get_settings

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(health_router_module, "get_session", sessionmaker(engine))
    monkeypatch.setattr(health, "scheduler_running", lambda: True)
    monkeypatch.setattr(get_settings().download_settings, "download_root", tmp_path)
    app = FastAPI()
    app.include_router(health_router_module.router, prefix="/api")
    yield TestClient(app)
    engine.dispose()


def _usage(free):
    return lambda _path: namedtuple("Usage", "total used free")(100 * 1024**3, 0, free)


def test_healthy_with_a_database_a_scheduler_and_room_to_download(client, monkeypatch):
    from backend.services import health

    monkeypatch.setattr(health.shutil, "disk_usage", _usage(50 * 1024**3))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {check["name"]: check["status"] for check in body["checks"]} == {
        "database": "ok", "scheduler": "ok", "disk": "ok",
    }
    assert body["disk"]["freeBytes"] == 50 * 1024**3


def test_little_free_space_is_a_warning_and_still_healthy(client, monkeypatch):
    from backend.services import health

    monkeypatch.setattr(health.shutil, "disk_usage", _usage(10 * 1024**2))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "warning"


def test_a_stopped_scheduler_is_unhealthy(client, monkeypatch):
    from backend.services import health

    monkeypatch.setattr(health, "scheduler_running", lambda: False)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_metrics_are_off_by_default(client):
    assert client.get("/api/metrics").status_code == 404


def test_metrics_report_health_and_counts_when_turned_on(client, monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings().health, "metrics_enabled", True)

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "vodloft_healthy 1" in response.text
    assert 'vodloft_health_check{check="database"} 1' in response.text
    assert "# TYPE vodloft_episodes gauge" in response.text
