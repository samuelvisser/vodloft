"""SoundCloud: searched through yt-dlp, which finds tracks, with the accounts behind them first; and the short links
its apps share, which lead to its own pages."""
from __future__ import annotations

import pytest

from sources import LinkKind
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource, sites
from sources.ytdlp.site_implementations import IMPLEMENTATIONS
from sources.ytdlp.site_implementations import other_sites

SOUNDCLOUD = sites.site_of("soundcloud")
SHARE_LINK = "https://on.soundcloud.com/xUUwSHL3lvECsqo8Lo"


def _track(track_id: str, account: str, name: str, title: str) -> dict:
    return {
        "id": track_id, "title": title, "uploader": name, "uploader_url": f"https://soundcloud.com/{account}",
        "webpage_url": f"https://soundcloud.com/{account}/{track_id}", "duration": 229.5, "timestamp": 1588291200,
        "view_count": 200_100,
        "thumbnails": [{"id": "large", "url": f"https://i1.sndcdn.com/{track_id}-large.jpg"},
                       {"id": "t500x500", "url": f"https://i1.sndcdn.com/{track_id}-t500x500.jpg"},
                       {"id": "original", "url": f"https://i1.sndcdn.com/{track_id}-original.png"}],
    }


@pytest.fixture
def searches(monkeypatch):
    calls = []

    def run_json(*args, **_kwargs):
        calls.append(args)
        return {"entries": [
            _track("remix", "eliramzy", "Eli Ramzy", "God Only Knows (Remix)"),
            _track("together", "forkingandcountry", "for KING & COUNTRY", "TOGETHER"),
            _track("shoulders", "forkingandcountry", "for KING & COUNTRY", "Shoulders"),
        ]}

    monkeypatch.setattr(runner, "run_json", run_json)
    monkeypatch.setattr(IMPLEMENTATIONS["soundcloud"], "avatar", lambda self, root: f"{root}/avatar.jpg")
    return calls


def test_youtube_and_soundcloud_are_searched_each_on_their_own():
    assert [(site.key, site.name, site.costly_search) for site in YtDlpSource().search_sites] == [
        ("youtube", "YouTube", True), ("soundcloud", "SoundCloud", True)]


def test_a_search_finds_tracks_and_the_accounts_that_made_most_of_them_first(searches):
    results = YtDlpSource().search(SOUNDCLOUD, "for king and country").results

    assert searches == [("--flat-playlist", "scsearch20:for king and country")]
    assert [(r.kind, r.kind_label, r.title, r.url, r.facts) for r in results[:2]] == [
        (LinkKind.COLLECTION, "Account", "for KING & COUNTRY", "https://soundcloud.com/forkingandcountry", ("2 matching tracks",)),
        (LinkKind.COLLECTION, "Account", "Eli Ramzy", "https://soundcloud.com/eliramzy", ("1 matching track",)),
    ]
    assert results[0].image_url == "https://soundcloud.com/forkingandcountry/avatar.jpg"
    track = results[3]
    assert (track.kind, track.kind_label, track.title, track.author_name, track.url) == (
        LinkKind.VIDEO, "Track", "TOGETHER", "for KING & COUNTRY", "https://soundcloud.com/forkingandcountry/together")
    assert track.image_url == "https://i1.sndcdn.com/together-t500x500.jpg"
    assert track.facts == ("3:49", "1 May 2020", "200.1K plays")


def test_an_account_found_can_be_added_as_a_creator(searches):
    from backend.api.endpoints.sources.service import search_source
    from backend.security.access import Access

    results = search_source(Access.full(), YtDlpSource(), "soundcloud", "for king and country").results

    assert [(result.slug, result.creator_names and result.creator_names.singular) for result in results[:3]] == [
        ("forkingandcountry", "creator"), ("eliramzy", "creator"), ("remix", None)]


class _Redirect:
    def __init__(self, location: str):
        self.headers = {"Location": location}
        self.is_redirect = True


def test_a_share_link_from_the_app_is_the_page_it_leads_to(monkeypatch):
    monkeypatch.setattr(other_sites.requests, "head", lambda url, **kwargs: _Redirect(
        "https://soundcloud.com/forkingandcountry?ref=clipboard&p=i&c=0&si=F286EC&utm_source=clipboard"))

    site = sites.site_for(SHARE_LINK)
    implementation = IMPLEMENTATIONS[site.key](site, runner.run_json)

    assert site.key == "soundcloud"
    page = implementation.full_link(SHARE_LINK)
    assert page == "https://soundcloud.com/forkingandcountry"
    assert implementation.creator_page(page) == "https://soundcloud.com/forkingandcountry"


def test_a_share_link_that_leads_off_soundcloud_is_left_as_it_is(monkeypatch):
    monkeypatch.setattr(other_sites.requests, "head", lambda url, **kwargs: _Redirect("https://example.com/elsewhere"))
    site = sites.site_for(SHARE_LINK)

    assert IMPLEMENTATIONS[site.key](site, runner.run_json).full_link(SHARE_LINK) == SHARE_LINK
