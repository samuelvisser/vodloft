from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_onboarding_status_creates_the_single_settings_row(monkeypatch):
    from backend.api.endpoints.onboarding import service
    from backend.db import Base
    from backend.db.models import Settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(admin_auth=SimpleNamespace(enabled=True)),
    )

    with Session(engine) as session:
        status = service.get_onboarding_status(session)
        session.commit()

        assert status.completed is False
        assert status.admin_password_configured is True
        [settings] = session.query(Settings).all()
        assert settings.onboarding_completed is False

    engine.dispose()


def test_complete_onboarding_is_persistent(monkeypatch):
    from backend.api.endpoints.onboarding import service
    from backend.db import Base
    from backend.db.models import Settings

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(admin_auth=SimpleNamespace(enabled=False)),
    )

    with Session(engine) as session:
        status = service.complete_onboarding(session)
        session.commit()

        assert status.completed is True
        assert status.admin_password_configured is False
        assert session.query(Settings).one().onboarding_completed is True

    with Session(engine) as session:
        assert service.get_onboarding_status(session).completed is True

    engine.dispose()


def _profiles(session) -> list[str]:
    from backend.db.models import LocalMediaProfileBase

    return sorted(slug for (slug,) in session.query(LocalMediaProfileBase.slug))


def test_finishing_without_an_import_adds_the_fresh_start_profiles_once(monkeypatch):
    from backend.api.endpoints.onboarding import service
    from backend.db import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(admin_auth=SimpleNamespace(enabled=False)))

    with Session(engine) as session:
        service.start_fresh(session)
        service.complete_onboarding(session)
        service.complete_onboarding(session)
        session.commit()
        assert _profiles(session) == ["vodloft-collections-audio", "vodloft-collections-video"]

    engine.dispose()


def test_finishing_after_an_import_keeps_only_the_imported_profiles(monkeypatch):
    from backend.api.endpoints.onboarding import service
    from backend.db import Base
    from backend.db.models import ImportRun

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(admin_auth=SimpleNamespace(enabled=False)))

    with Session(engine) as session:
        session.add(ImportRun(importer="pinchflat", status="finished", options={}, report=[], counts={}))
        session.flush()
        service.complete_onboarding(session)
        session.commit()
        assert _profiles(session) == []

    engine.dispose()
