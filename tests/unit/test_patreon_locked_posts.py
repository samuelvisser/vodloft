"""Patreon through its own API: a creator's posts with their video or sound, locked by the least pledge that unlocks
them without a failing yt-dlp lookup each, and their collections as playlists."""
from __future__ import annotations

import pytest

from sources import ItemRef, ListOrder
from sources import ytdlp_runner as runner
from sources.contract import Access, cheapest, pledge_amount, pledge_key
from sources.ytdlp import YtDlpSource, sites
from sources.ytdlp.site_implementations.patreon import PatreonImplementation

from test_quick_check import session  # noqa: F401

CAMPAIGN = "https://www.patreon.com/c/creator"
ROOT = "https://www.patreon.com/creator"
NO_ACCESS = "You do not have access to this post"

IDS = {"open": "125257910", "paid": "121848656", "text": "116397886", "tier": "110000001"}
DATES = {"open": "2024-03-01", "paid": "2024-02-01", "text": "2024-01-15", "tier": "2024-01-01"}


def _post_url(name: str) -> str:
    return f"https://www.patreon.com/posts/{name}-{IDS[name]}"


def _post(name: str, *, kind: str = "video_embed", viewable: bool = False, rules: tuple[str, ...] = ("patrons",)) -> dict:
    return {
        "type": "post", "id": IDS[name],
        "attributes": {
            "title": f"Post {name}", "post_type": kind, "current_user_can_view": viewable, "url": _post_url(name),
            "published_at": f"{DATES[name]}T12:00:00.000+00:00", "teaser_text": f"About {name}",
            "thumbnail": {"large": f"https://c10.patreonusercontent.com/p/post/{IDS[name]}/1.jpg?token-hash=x"},
        },
        "relationships": {"access_rules": {"data": [{"type": "access-rule", "id": rule} for rule in rules]}},
    }


# Patreon's access rules: any patron, a pledge of at least $5, or either of two tiers, the cheapest $3.
RULES = [
    {"type": "access-rule", "id": "patrons", "attributes": {"access_rule_type": "patrons", "currency": "USD"}},
    {"type": "access-rule", "id": "five", "attributes": {"access_rule_type": "min_cents_pledged", "amount_cents": 500, "currency": "USD"}},
    {"type": "access-rule", "id": "gold", "attributes": {"access_rule_type": "tier", "currency": "USD"},
     "relationships": {"tier": {"data": {"type": "reward", "id": "gold"}}}},
    {"type": "access-rule", "id": "silver", "attributes": {"access_rule_type": "tier", "currency": "USD"},
     "relationships": {"tier": {"data": {"type": "reward", "id": "silver"}}}},
    {"type": "reward", "id": "gold", "attributes": {"amount_cents": 1000, "currency": "USD"}},
    {"type": "reward", "id": "silver", "attributes": {"amount_cents": 300, "currency": "USD"}},
]


class FakePatreon:
    """Patreon's API for one creator: an open video, a video for $5 patrons, a locked text post and a video for two
    tiers; and two collections, one kept newest first in the creator's own order."""

    def __init__(self) -> None:
        self.posts = {
            "open": _post("open", kind="video_external_file", viewable=True, rules=()),
            "paid": _post("paid", rules=("five",)),
            "text": _post("text", kind="text_only"),
            "tier": _post("tier", kind="podcast", rules=("gold", "silver")),
        }
        self.collections = {
            "71": {"title": "Season one", "post_ids": [IDS["paid"], IDS["tier"]], "post_sort_type": "custom", "num_posts": 2,
                   "created_at": "2024-01-01T00:00:00+00:00"},
            "72": {"title": "Old to new", "post_ids": [IDS["tier"], IDS["open"]], "post_sort_type": "custom", "num_posts": "2",
                   "created_at": "2024-02-01T00:00:00+00:00"},
            "73": {"title": "Empty", "post_ids": [], "post_sort_type": "custom", "num_posts": 0, "created_at": "2024-03-01T00:00:00+00:00"},
        }
        self.asked: list[str] = []

    def __call__(self, endpoint: str, query: dict[str, str]) -> dict:
        self.asked.append(endpoint)
        campaign = {"type": "campaign", "id": "9", "attributes": {"name": "The Creator", "vanity": "creator", "url": ROOT}}
        if endpoint == "search":
            return {"data": [{"type": "campaign-document", "id": "campaign_9", "attributes": {"url": ROOT}}]}
        if endpoint == "campaigns/9":
            return {"data": {**campaign, "attributes": {**campaign["attributes"], "summary": "Videos", "avatar_photo_url": "https://c10/a.jpg"}}}
        if endpoint == "posts":
            wanted = self.posts.values()
            if collection := query.get("filter[collection_id]"):
                ids = self.collections[collection]["post_ids"]
                wanted = [post for post in wanted if post["id"] in ids]
            ordered = sorted(wanted, key=lambda post: post["attributes"]["published_at"], reverse=True)
            return {"data": ordered, "included": RULES, "meta": {"pagination": {"cursors": {"next": None}}}}
        if endpoint.startswith("posts/"):
            post = next(post for post in self.posts.values() if post["id"] == endpoint.removeprefix("posts/"))
            return {"data": post, "included": RULES}
        if endpoint.startswith("collection/"):
            return {"data": {"attributes": self.collections[endpoint.removeprefix("collection/")]}, "included": [campaign]}
        if endpoint == "collection":
            return {"data": [{"id": key, "attributes": value} for key, value in self.collections.items()]}
        raise AssertionError(endpoint)


@pytest.fixture
def patreon(monkeypatch):
    api = FakePatreon()
    monkeypatch.setattr(PatreonImplementation, "call", staticmethod(api))
    looked_up: list[str] = []

    def run_json(*args, **_kwargs):
        url = args[-1]
        looked_up.append(url)
        name = next(name for name, number in IDS.items() if url.endswith(number))
        if not api.posts[name]["attributes"]["current_user_can_view"] and "--ignore-no-formats-error" not in args:
            raise runner.YtDlpError(f"[patreon] {IDS[name]}: {NO_ACCESS}")
        return {
            "id": IDS[name], "extractor_key": "Patreon", "title": f"Post {name}", "webpage_url": url, "upload_date": "20240101",
            "formats": [{"url": "https://cdn.example/v.mp4"}] if api.posts[name]["attributes"]["current_user_can_view"] else [],
        }

    def run_json_lines(*args, **_kwargs):
        infos, errors = [], {}
        for url in [arg for arg in args if arg.startswith("https://")]:
            try:
                infos.append({**run_json(*args, url), "original_url": url})
            except runner.YtDlpError as exc:
                post_id, message = str(exc).split("] ", 1)[1].split(": ", 1)
                errors[post_id] = message
        return infos, errors

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr(runner, "run_json_lines", run_json_lines)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)
    return api, looked_up


def test_locked_posts_come_from_patreons_api_and_only_open_ones_are_looked_up(patreon):
    _api, looked_up = patreon
    found = {video.slug: video for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}

    # The text post is left out.
    assert set(found) == {f"patreon-{IDS[name]}" for name in ("open", "paid", "tier")}
    assert found[f"patreon-{IDS['open']}"].access is None
    paid = found[f"patreon-{IDS['paid']}"]
    assert (paid.title, paid.access, paid.access_refused, paid.description) == ("Post paid", "pledge-500-usd", True, "About paid")
    assert paid.image_url.startswith("https://c10.patreonusercontent.com/")
    # Of two tiers, the cheapest unlocks the post.
    assert found[f"patreon-{IDS['tier']}"].access == "pledge-300-usd"
    # yt-dlp only looked up the post the account may view.
    assert looked_up == [_post_url("open")]


def test_a_known_post_is_not_looked_up_again(patreon):
    known = frozenset({f"patreon-{IDS[name]}" for name in ("open", "paid", "tier")})

    assert list(YtDlpSource().list_episodes(CAMPAIGN, known=known)) == []


def test_a_locked_post_looked_up_on_its_own_gets_the_pledge_that_unlocks_it(patreon):
    refresh = YtDlpSource().check_pending([ItemRef("paid", _post_url("paid"))])

    assert refresh.details["paid"].access == "pledge-500-usd"
    assert refresh.details["paid"].access_refused


def test_patreon_names_its_tiers_by_their_least_pledge():
    site = sites.site_for(CAMPAIGN)

    assert site.access(sites.MEMBERS_KEY).label == "Patrons only"
    five = site.access(pledge_key(500, "USD"))
    assert (five.label, five.tier) == ("Patrons from $5", 500)
    assert five.description == "Only the creator's patrons who pledge $5 or more can watch this."
    assert pledge_amount(pledge_key(250, "EUR")) == "€2.50"
    assert pledge_amount(pledge_key(700, "SEK")) == "7 SEK"
    # A site without tiers of its creators' own knows no pledges.
    assert sites.site_for("https://www.youtube.com/watch?v=a").access(pledge_key(500, "USD")) is None


def test_a_higher_tier_gives_what_a_lower_one_does():
    insider, plus = Access("insider", "Insider", "", tier=2), Access("plus", "Insider Plus", "", tier=3)
    members = Access("members", "Members only", "")

    assert plus.gives(insider) and not insider.gives(plus)
    assert members.gives(members) and not members.gives(insider)
    assert cheapest([plus, None, insider]) is insider
    assert cheapest([members]) is members and cheapest([]) is None


def test_a_picture_patreon_does_not_serve_is_left_out(monkeypatch):
    # Patreon gives embedded videos and links a picture on its media-u address, which answers with an error page.
    pictures = {
        "open": "https://www.patreon.com/media-u/v3/33031817",
        "paid": "https://c10.patreonusercontent.com/4/patreon-media/p/post/121848656/abc/eyJ3IjoxMDgwfQ%3D%3D/1.jpg",
    }

    def run_json(*args, **_kwargs):
        name = next(name for name, number in IDS.items() if args[-1].endswith(number))
        return {"id": IDS[name], "extractor_key": "Patreon", "title": name, "webpage_url": args[-1], "thumbnail": pictures[name],
                "formats": [{"url": "https://cdn.example/v.mp4"}]}

    monkeypatch.setattr(runner, "run_json", run_json)
    source = YtDlpSource()

    assert source.video_details(_post_url("open")).image_url is None
    assert source.video_details(_post_url("paid")).image_url == pictures["paid"]


def test_a_creator_has_their_posts_and_their_collections_as_playlists(patreon):
    from progress_plan import PlanTracker

    source = YtDlpSource()
    creator = source.creator_details(CAMPAIGN, PlanTracker())

    assert (creator.ref, creator.url, creator.title, creator.avatar_url) == ("creator", ROOT, "The Creator", "https://c10/a.jpg")
    feed, *playlists = creator.sections
    assert (feed.ref, feed.url, feed.title) == ("posts", f"{ROOT}/posts", "Posts")
    # Newest first, and only those with posts.
    assert [(section.title, section.url, section.item_count) for section in playlists] == [
        ("Old to new", "https://www.patreon.com/collection/72", 2),
        ("Season one", "https://www.patreon.com/collection/71", 2),
    ]
    assert {section.type.names.singular for section in playlists} == {"playlist"}
    assert [section.title for section in source.season_lists(CAMPAIGN)] == ["Old to new", "Season one"]


def test_links_of_a_creator_and_of_a_playlist(patreon):
    source = YtDlpSource()

    for page in (CAMPAIGN, ROOT, f"{ROOT}/posts", "https://patreon.com/cw/creator"):
        assert source.is_creator_page(page), page
        assert source.creator_of(page) == ROOT
    assert not source.is_creator_page(_post_url("open"))
    playlist = "https://www.patreon.com/collection/71"
    assert source.is_list(playlist) and not source.is_creator_page(playlist)
    assert source.creator_of(playlist) == ROOT
    assert source.collection_details(playlist).title == "Season one"


def test_a_playlist_lists_its_posts_the_first_first(patreon):
    api, _ = patreon
    source = YtDlpSource()

    # The creator's own order that is just newest first counts as newest first.
    assert [item.slug for item in source.list_items("https://www.patreon.com/collection/71")] == [
        f"patreon-{IDS['tier']}", f"patreon-{IDS['paid']}",
    ]
    # Any other order of the creator's own is kept.
    api.collections["72"]["post_ids"] = [IDS["paid"], IDS["open"], IDS["tier"]]
    assert [item.slug for item in source.list_items("https://www.patreon.com/collection/72")] == [
        f"patreon-{IDS['paid']}", f"patreon-{IDS['open']}", f"patreon-{IDS['tier']}",
    ]
    assert sites.site_for(CAMPAIGN).list_order is ListOrder.OLDEST_FIRST


def _listed_titles(session, sharing_url, listed):  # noqa: F811
    from datetime import datetime, timezone

    from backend.db.models import Collection, Episode
    from sources import VideoDetails
    from task_manager.tasks.helpers.listed_collections import add_listed_episodes

    collection = Collection(
        uuid="uuid-list", slug="a-list", source_key="ytdlp", title="A list", kind="list",
        sharing_url=sharing_url, membership_level="FREE", type="series", episode_identifier="numbered",
        author_name="A", author_slug="a",
    )
    session.add(collection)
    session.commit()
    found = [
        VideoDetails(
            slug=f"video-{name}", url=url, title=name,
            published_at=datetime(2024, 1, day, tzinfo=timezone.utc) if day else None,
        )
        for name, url, day in listed
    ]
    add_listed_episodes(session, collection_id=collection.id, found=found)
    session.commit()
    episodes = session.query(Episode).filter(Episode.collection_id == collection.id).order_by(Episode.index)
    return [episode.title for episode in episodes]


def test_a_newest_first_listing_is_added_the_other_way_around(session):  # noqa: F811
    # Rumble lists a channel newest first: the oldest is the first episode, whatever the videos' dates say.
    listed = [(name, f"https://rumble.com/v{name}-video.html", None) for name in ("c", "b", "a")]

    assert _listed_titles(session, "https://rumble.com/c/creator", listed) == ["a", "b", "c"]


def test_a_collection_on_a_site_without_an_order_of_its_own_numbers_by_date(session):  # noqa: F811
    # A site VODLoft has no contract for lists in no order it can trust.
    listed = [(name, f"https://videos.example.com/watch/{name}", day) for name, day in (("b", 2), ("c", 3), ("a", 1))]

    assert _listed_titles(session, "https://videos.example.com/list/1", listed) == ["a", "b", "c"]


def test_each_site_says_what_order_it_lists_in():
    assert sites.site_for("https://www.youtube.com/playlist?list=PL1").list_order is ListOrder.OLDEST_FIRST
    assert sites.site_for("https://rumble.com/c/creator").list_order is ListOrder.NEWEST_FIRST
    assert sites.site_for("https://videos.example.com/list/1").list_order is ListOrder.NONE
