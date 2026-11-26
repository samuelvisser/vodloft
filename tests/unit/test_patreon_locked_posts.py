"""Patreon posts for patrons only are kept as locked episodes, not dropped, so a collection of a paid Patreon finds them."""
from __future__ import annotations

import pytest

from sources import ItemRef
from sources.ytdlp import sites
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource
from sources.ytdlp.site_implementations.patreon import PatreonImplementation

from test_quick_check import session  # noqa: F401

CAMPAIGN = "https://www.patreon.com/creator"
NO_ACCESS = "You do not have access to this post"
NO_MEDIA = "No supported media found in this post"


IDS = {"open": "125257910", "paid": "121848656", "text": "116397886"}


def _post_url(post_id: str) -> str:
    return f"https://www.patreon.com/Creator/posts/early-access-{IDS[post_id]}"


def _post(post_id: str, **fields) -> dict:
    return {
        "id": IDS[post_id], "extractor_key": "Patreon", "title": f"Post {post_id}", "webpage_url": _post_url(post_id),
        "upload_date": "20261120", **fields,
    }


@pytest.fixture
def patreon(monkeypatch):
    """A campaign of an open video, a post for patrons only and a text post, as yt-dlp answers without cookies."""
    refused = {"open": None, "paid": NO_ACCESS, "text": NO_MEDIA}
    # What Patreon's API says each post is.
    kinds = {IDS["open"]: "video_external_file", IDS["paid"]: "video_embed", IDS["text"]: "text_only"}

    def run_json(*args, **_kwargs):
        url = args[-1]
        if url == CAMPAIGN:
            # Patreon's listing gives each post by its link alone, without its id or title.
            return {"_type": "playlist", "id": "1", "extractor_key": "PatreonCampaign", "entries": [
                {"_type": "url", "url": _post_url(post_id), "ie_key": "Patreon"} for post_id in refused
            ]}
        post_id = next(name for name, number in IDS.items() if url.endswith(number))
        if refused[post_id] and "--ignore-no-formats-error" not in args:
            raise runner.YtDlpError(f"[patreon] {IDS[post_id]}: {refused[post_id]}")
        return _post(post_id, formats=[] if refused[post_id] else [{"url": "https://cdn.example/v.mp4"}])

    def run_json_lines(*args, **_kwargs):
        urls = [arg for arg in args if arg.startswith("https://")]
        infos, errors = [], {}
        for url in urls:
            try:
                infos.append({**run_json(*args, url), "original_url": url})
            except runner.YtDlpError as exc:
                post_id, message = str(exc).split("] ", 1)[1].split(": ", 1)
                errors[post_id] = message
        return infos, errors

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr(runner, "run_json_lines", run_json_lines)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)
    monkeypatch.setattr(PatreonImplementation, "_post_kinds", staticmethod(lambda campaign_id, wanted: dict(kinds)))
    return refused, kinds


def test_a_post_for_patrons_only_is_listed_locked_and_a_text_post_is_left_out(patreon):
    found = {video.slug: video for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}

    assert set(found) == {"patreon-125257910", "patreon-121848656"}
    assert found["patreon-125257910"].access is None
    assert (found["patreon-121848656"].title, found["patreon-121848656"].access) == ("Post paid", sites.MEMBERS_KEY)


def test_a_known_post_is_not_looked_up_again(patreon):
    known = frozenset({"patreon-125257910", "patreon-121848656"})

    assert list(YtDlpSource().list_episodes(CAMPAIGN, known=known)) == []


def test_a_post_for_patrons_only_is_looked_up_locked_on_its_own(patreon):
    refresh = YtDlpSource().check_pending([ItemRef("paid", _post_url("paid")), ItemRef("text", _post_url("text"))])

    assert set(refresh.details) == {"paid"}
    assert refresh.details["paid"].access == sites.MEMBERS_KEY
    assert not refresh.removed


def test_patreon_calls_its_locked_posts_patrons_only():
    access = sites.site_for(CAMPAIGN).access(sites.MEMBERS_KEY)
    assert access.label == "Patrons only"


def test_a_picture_patreon_does_not_serve_is_left_out(monkeypatch):
    # Patreon gives embedded videos and links a picture on its media-u address, which answers with an error page.
    pictures = {
        "open": "https://www.patreon.com/media-u/v3/33031817",
        "paid": "https://c10.patreonusercontent.com/4/patreon-media/p/post/121848656/abc/eyJ3IjoxMDgwfQ%3D%3D/1.jpg",
    }

    def run_json(*args, **_kwargs):
        post_id = next(name for name, number in IDS.items() if args[-1].endswith(number))
        return _post(post_id, thumbnail=pictures[post_id], formats=[{"url": "https://cdn.example/v.mp4"}])

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)
    source = YtDlpSource()

    assert source.video_details(_post_url("open")).image_url is None
    assert source.video_details(_post_url("paid")).image_url == pictures["paid"]


def test_a_text_post_for_patrons_only_is_left_out(patreon):
    # yt-dlp refuses a locked text post just like a locked video, so only Patreon's API tells them apart.
    refused, kinds = patreon
    refused["text"] = NO_ACCESS

    found = {video.slug for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}
    assert found == {"patreon-125257910", "patreon-121848656"}

    kinds[IDS["text"]] = "audio_file"
    found = {video.slug for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}
    assert "patreon-116397886" in found


def test_every_post_is_kept_when_patreon_does_not_tell_their_kinds(patreon, monkeypatch):
    refused, _ = patreon
    refused["text"] = NO_ACCESS

    def refuse(campaign_id, wanted):
        raise RuntimeError("Patreon said no")

    monkeypatch.setattr(PatreonImplementation, "_post_kinds", staticmethod(refuse))
    found = {video.slug for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}
    assert found == {"patreon-125257910", "patreon-121848656", "patreon-116397886"}


def _listed_titles(session, sharing_url, listed):
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


def test_a_patreon_collection_adds_its_newest_first_posts_the_other_way_around(session):
    # Patreon lists a creator's posts newest first: the oldest is the first episode, whatever the posts' dates say.
    listed = [(name, _post_url(name), None) for name in ("open", "paid", "text")]

    assert _listed_titles(session, CAMPAIGN, listed) == ["text", "paid", "open"]


def test_a_collection_on_a_site_without_an_order_of_its_own_numbers_by_date(session):
    # A site VODLoft has no contract for lists in no order it can trust.
    listed = [(name, f"https://videos.example.com/watch/{name}", day) for name, day in (("b", 2), ("c", 3), ("a", 1))]

    assert _listed_titles(session, "https://videos.example.com/list/1", listed) == ["a", "b", "c"]


def test_a_playlist_keeps_its_own_order():
    from sources import ListOrder
    from sources.ytdlp import sites

    assert sites.site_for("https://www.youtube.com/playlist?list=PL1").list_order is ListOrder.OLDEST_FIRST
    assert sites.site_for("https://www.patreon.com/c/davidwood").list_order is ListOrder.NEWEST_FIRST
    assert sites.site_for("https://videos.example.com/list/1").list_order is ListOrder.NONE
