"""The collection health check: finding the creator behind collections, and suggesting grouping a creator's
collections."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from sources import CreatorDetails, Feature, Site
from test_ytdlp_collections import ListedSource, session  # noqa: F401


class CreatorsSource(ListedSource):
    """A Site with creators: each link's path names its creator."""

    id = "creators"
    domains = ("creators.example",)
    features = ListedSource.features | {Feature.CREATORS}
    sites = (Site("creators", "Creators", ("creators.example",), creators=True),)

    def __init__(self):
        super().__init__()
        self.asked: list[str] = []

    def site_for(self, url):
        return self.sites[0]

    def creator_of(self, url):
        self.asked.append(url)
        return url.split("/")[3]

    def creator_details(self, ref, plan=None):
        return CreatorDetails(ref=ref, url=f"https://creators.example/{ref}", title=ref.title())


@pytest.fixture
def source(monkeypatch):
    from backend.services import sites
    from sources import registry

    monkeypatch.setattr(registry, "_sources", dict(registry._sources))
    sites._site_of.cache_clear()
    yield registry.register(CreatorsSource())
    sites._site_of.cache_clear()


def _collections(session, *links):
    from backend.db.models import Collection

    for number, link in enumerate(links, start=1):
        session.add(Collection(
            uuid=f"uuid-{number}", slug=f"c{number}", source_key="creators", site_key="creators", title=f"C{number}",
            sharing_url=f"https://creators.example/{link}", membership_level="FREE", type="series",
            episode_identifier="seasonal", author_name="Ann", author_slug="ann",
        ))
    session.commit()
    return [collection.id for collection in session.scalars(select(Collection).order_by(Collection.id))]


def _check(ids):
    from backend.services.collection_health import find_site_creator

    return [find_site_creator(collection_id) for collection_id in ids]


def test_three_collections_of_one_creator_are_suggested_once_their_creator_is_found(source, session):
    from backend.services.collection_health import creator_suggestions

    ids = _collections(session, "ann/a", "ann/b", "bob/c", "ann/d")
    assert creator_suggestions(session) == []
    session.rollback()

    assert _check(ids) == [True] * 4
    # A collection is looked up once for its link.
    assert _check(ids) == [False] * 4
    assert len(source.asked) == 4

    [suggestion] = creator_suggestions(session)
    assert (suggestion.ref, suggestion.title, [c.slug for c in suggestion.collections]) == ("ann", "Ann", ["c1", "c2", "c4"])
    assert suggestion.creator_slug is None


def test_later_hides_a_suggestion_for_a_week_and_dismiss_for_good_until_reset(source, session):
    from backend.db.core import run_write_transaction
    from backend.services.collection_health import (
        creator_subject, creator_suggestions, dismissed_count, put_off_suggestion, reset_dismissals,
    )
    from backend.types.collection_health_types import HealthIssueKind

    _check(_collections(session, "ann/a", "ann/b", "ann/c"))
    now = datetime.now(timezone.utc)
    subject = creator_subject("creators", "ann")

    run_write_transaction(lambda s: put_off_suggestion(s, HealthIssueKind.CREATORS, subject, for_good=False, now=now))
    assert creator_suggestions(session, now + timedelta(days=6)) == []
    assert len(creator_suggestions(session, now + timedelta(days=8))) == 1

    run_write_transaction(lambda s: put_off_suggestion(s, HealthIssueKind.CREATORS, subject, for_good=True))
    assert creator_suggestions(session, now + timedelta(days=30)) == []
    assert dismissed_count(session) == 1
    session.rollback()

    run_write_transaction(reset_dismissals)
    assert len(creator_suggestions(session)) == 1


def test_turning_the_creators_check_off_hides_its_suggestions(source, session):
    from backend.db.core import run_write_transaction
    from backend.services.collection_health import creator_suggestions, set_check
    from backend.types.collection_health_types import HealthIssueKind

    _check(_collections(session, "ann/a", "ann/b", "ann/c"))
    run_write_transaction(lambda s: set_check(s, HealthIssueKind.CREATORS, False))
    assert creator_suggestions(session) == []
    session.rollback()
    run_write_transaction(lambda s: set_check(s, HealthIssueKind.CREATORS, True))
    assert len(creator_suggestions(session)) == 1


def test_grouping_a_suggestion_puts_its_collections_in_one_new_creator(source, session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.endpoints.collections import router
    from backend.db.models import Collection

    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")

    _check(_collections(session, "ann/a", "ann/b", "ann/c"))
    session.rollback()

    with TestClient(app) as client:
        response = client.post("/api/v1/collections/health/creators/creators/ann/group")
        assert response.status_code == 200, response.text
        assert response.json() == {"creatorSlug": "ann"}
        assert client.get("/api/v1/collections/health").json()["creatorSuggestions"] == []

    session.expire_all()
    creator_ids = {collection.creator_id for collection in session.scalars(select(Collection))}
    assert len(creator_ids) == 1 and None not in creator_ids
