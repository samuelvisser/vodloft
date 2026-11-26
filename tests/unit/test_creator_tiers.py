"""Tiers creators set up themselves, such as Patreon's: VODLoft keeps them with ids of its own, and media points to them,
so it stays with its tier when the creator renames it or changes what it costs."""
from __future__ import annotations

from dataclasses import replace

import pytest
from sources import CreatorTier as SiteTier
from sources import registry
from test_ytdlp_collections import ListedSource, _video, session  # noqa: F401

CREATOR = "https://www.patreon.com/creator"


class TieredSource(ListedSource):
    """Lists a Patreon creator's posts, one for patrons on the creator's Fiver tier, and tells the creator's tiers."""

    id = "ytdlp"

    def __init__(self):
        super().__init__()
        self.tiers = (SiteTier("bronze", "Bronze", "$1", 100), SiteTier("fiver", "Fiver", "$5", 500))
        self.asked: list[str] = []

    def site_for(self, url):
        from sources.ytdlp import YtDlpSource

        return YtDlpSource().site_for(url)

    def site_of(self, site_key):
        from sources.ytdlp import YtDlpSource

        return YtDlpSource().site_of(site_key)

    def creator_tiers(self, url):
        self.asked.append(url)
        return self.tiers


@pytest.fixture
def tiered(monkeypatch):
    sources = dict(registry._sources)
    sources.pop("ytdlp", None)
    monkeypatch.setattr(registry, "_sources", sources)
    return registry.register(TieredSource())


def _post(slug: str, access: str | None) -> object:
    video = _video(slug, 2024)
    return replace(video, url=f"https://www.patreon.com/posts/{slug}", access=access, access_refused=access is not None)


def _creator(session):  # noqa: F811
    from backend.db.models import Collection

    collection = Collection(
        uuid="uuid-creator", slug="creator", source_key="ytdlp", title="The Creator", sharing_url=CREATOR,
        membership_level="FREE", type="series", episode_identifier="date_based", author_name="The Creator",
        author_slug="creator",
    )
    session.add(collection)
    session.commit()
    return collection


def _label(episode) -> str:
    from backend.services.media_access import media_access

    return media_access(episode).label


def test_an_episode_keeps_its_tier_when_the_creator_renames_it(tiered, session):  # noqa: F811
    from backend.db.models import CreatorTier, Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _creator(session)
    tiered.videos = [_post("paid", "tier:fiver"), _post("members", "members"), _post("open", None)]
    index_listed_collection(session, collection_id=collection.id, source=tiered)
    session.commit()

    episodes = {episode.video_slug: episode for episode in session.query(Episode)}
    paid = episodes["paid"]
    # The episode points to the tier VODLoft keeps, which knows Patreon's id of it.
    assert paid.access == "tier" and paid.creator_tier.site_tier_id == "fiver"
    assert paid.access_refused_at is not None
    assert (_label(paid), media_description(paid)) == (
        "Fiver", "Only patrons on the creator's “Fiver” tier ($5) or higher can watch this.",
    )
    assert episodes["members"].creator_tier is None and _label(episodes["members"]) == "Patrons only"
    assert episodes["open"].access is None and episodes["open"].creator_tier is None
    assert {(tier.site_tier_id, tier.name, tier.rank) for tier in session.query(CreatorTier)} == {
        ("bronze", "Bronze", 100), ("fiver", "Fiver", 500),
    }
    kept = paid.creator_tier.id

    # The creator renames the tier and asks more for it: the episode stays with it.
    tiered.tiers = (SiteTier("fiver", "Supporter", "$6", 600),)
    tiered.videos = []
    index_listed_collection(session, collection_id=collection.id, source=tiered)
    session.expire_all()
    paid = session.query(Episode).filter(Episode.video_slug == "paid").one()
    assert paid.creator_tier.id == kept
    assert (_label(paid), paid.creator_tier.amount, paid.creator_tier.rank) == ("Supporter", "$6", 600)


def media_description(episode) -> str:
    from backend.services.media_access import media_access

    return media_access(episode).description


def test_a_tier_vodloft_does_not_know_yet_is_a_paid_tier(tiered, session):  # noqa: F811
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _creator(session)
    tiered.tiers = ()
    tiered.videos = [_post("paid", "tier:new")]
    index_listed_collection(session, collection_id=collection.id, source=tiered)
    session.commit()

    paid = session.query(Episode).one()
    assert paid.creator_tier.site_tier_id == "new" and paid.creator_tier.name is None
    assert _label(paid) == "Paid tier"


def test_a_link_names_its_tier_by_the_sites_id_of_it(tiered, session):  # noqa: F811
    from backend.db.core import run_write_transaction
    from backend.services.creator_tiers import keep_tiers
    from backend.services.media_access import link_access

    run_write_transaction(lambda w: keep_tiers(w, "patreon", tiered.tiers))
    assert link_access("ytdlp", "https://www.patreon.com/posts/a-1", "tier:fiver").label == "Fiver"
    assert link_access("ytdlp", "https://www.patreon.com/posts/a-1", "tier:other").label == "Paid tier"


def test_a_tier_without_a_name_is_named_by_its_amount(tiered, session):  # noqa: F811
    from backend.db.models import Episode
    from task_manager.tasks.helpers.listed_collections import index_listed_collection

    collection = _creator(session)
    tiered.tiers = (SiteTier("fiver", None, "$5", 500),)
    tiered.videos = [_post("paid", "tier:fiver")]
    index_listed_collection(session, collection_id=collection.id, source=tiered)
    session.commit()

    assert _label(session.query(Episode).one()) == "Patrons from $5"
