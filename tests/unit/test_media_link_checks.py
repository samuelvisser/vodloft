"""Description links only become links to Add media once Add media's own lookup finds something there."""
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from backend.api.endpoints.sources import service
from backend.api.endpoints.sources.service import LinkChecks, LinkQuestion
from backend.security.access import Access


class _Source:
    def __init__(self, source_id, found=(), fails=False, gate=None):
        self.id, self.name = source_id, source_id
        self.found, self.fails, self.gate = set(found), fails, gate
        self.asked = []

    def resolve(self, url, plan=None):
        self.asked.append(url)
        if self.gate is not None:
            self.gate.wait(5)
        if self.fails:
            raise RuntimeError("the site did not answer")
        return SimpleNamespace(url=url) if url in self.found else None


@pytest.fixture(autouse=True)
def _no_source_options(monkeypatch):
    monkeypatch.setattr(service, "ytdlp_call_options", lambda source: nullcontext())


def _question(url, *sources):
    return LinkQuestion(url, list(sources), list(sources), False)


def test_a_link_works_when_a_source_finds_something_there():
    first, second = _Source("first"), _Source("second", found={"https://a.example/video"})
    checks = LinkChecks()

    assert checks.check(Access.full(), _question("https://a.example/video", first, second)).result(5) is True
    assert checks.check(Access.full(), _question("https://a.example/page", first, second)).result(5) is False


def test_an_answer_is_kept_and_a_link_being_checked_is_checked_once():
    gate = threading.Event()
    source = _Source("first", found={"https://a.example/video"}, gate=gate)
    checks = LinkChecks()

    running = [checks.check(Access.full(), _question("https://a.example/video", source)) for _ in range(3)]
    gate.set()
    assert [future.result(5) for future in running] == [True, True, True]
    assert checks.check(Access.full(), _question("https://a.example/video", source)).result(5) is True
    assert source.asked == ["https://a.example/video"]


def test_a_failed_lookup_is_not_a_link(monkeypatch):
    source = _Source("first", fails=True)
    checks = LinkChecks()

    assert checks.check(Access.full(), _question("https://a.example/video", source)).result(5) is False
    # Kept for a short while only, then asked again.
    monkeypatch.setattr(service.time, "monotonic", lambda: 10 ** 9)
    assert checks.check(Access.full(), _question("https://a.example/video", source)).result(5) is False
    assert len(source.asked) == 2


def test_the_api_says_whether_add_media_finds_something_at_a_link(monkeypatch):
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.api.endpoints.sources import router as source_router_module
    from backend.db.core import Base
    import backend.db.models  # noqa: F401  (registers every table)
    from conftest import use_database

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    use_database(engine)
    session = sessionmaker(bind=engine)()

    @contextmanager
    def db_session():
        yield session

    source = _Source("stub", found={"https://stub.example/watch/clip-1"})
    monkeypatch.setattr(service, "sources_for", lambda url, preferred=None: [source] if "stub.example" in url else [])
    monkeypatch.setattr(source_router_module, "db_session", db_session)
    monkeypatch.setattr(source_router_module, "link_checks", LinkChecks())
    monkeypatch.setattr(Access, "allows_link", lambda self, source_id, url: True)
    monkeypatch.setattr(Access, "check_link", lambda self, source, url: None)
    app = FastAPI()
    app.include_router(source_router_module.router, prefix="/api")
    with TestClient(app) as client:
        def works(url):
            response = client.post("/api/media-links/check", json={"url": url})
            assert response.status_code == 200, response.text
            return response.json()["works"]

        assert works("https://stub.example/watch/clip-1") is True
        assert works("https://stub.example/about") is False
        # No Source handles the link: nothing is asked.
        assert works("https://nothing.example/x") is False
    assert source.asked == ["https://stub.example/watch/clip-1", "https://stub.example/about"]
    session.close()
    engine.dispose()


def test_a_quick_first_look_with_a_title_is_enough():
    class Previewing(_Source):
        def preview(self, url):
            return SimpleNamespace(title="A video", image_url=None, author_name=None, site="Stub", kind="video", slug="a", url=url)

    source = Previewing("first")
    assert LinkChecks().check(Access.full(), _question("https://a.example/video", source)).result(5) is True
    # The full lookup, which a Site may count against the user, is not needed.
    assert source.asked == []
