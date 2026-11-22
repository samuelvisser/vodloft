"""SoundCloud: searched through SoundCloud's web API by way of yt-dlp's extractor, or with yt-dlp's track search when
that fails; and the short links its apps share, which lead to its own pages."""
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


class FakeExtractor:
    """yt-dlp's SoundCloud extractor, answering SoundCloud's web API with recorded answers."""

    _API_V2_BASE = "https://api-v2.soundcloud.com/"
    _HEADERS = {}
    answers: dict[str, list[dict]] = {}
    calls: list[tuple[str, dict]] = []

    def initialize(self):
        pass

    def _call_api(self, url, video_id, query=None, headers=None, note=None):
        endpoint = url.removeprefix(self._API_V2_BASE)
        self.calls.append((endpoint, query))
        if endpoint not in self.answers:
            raise RuntimeError("HTTP Error 401: Unauthorized")
        return {"collection": self.answers[endpoint]}


class FakeYoutubeDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_info_extractor(self, key):
        assert key == "Soundcloud"
        return FakeExtractor()


@pytest.fixture
def api(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    FakeExtractor.answers, FakeExtractor.calls = {}, []
    return FakeExtractor


@pytest.fixture
def searches(monkeypatch, api):
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
        ("youtube", "YouTube", True), ("twitch", "Twitch", False), ("soundcloud", "SoundCloud", True)]


def test_soundclouds_own_search_finds_accounts_albums_playlists_and_tracks(api):
    user = {"username": "for KING & COUNTRY", "avatar_url": "https://i1.sndcdn.com/avatars-fkac-large.jpg"}
    api.answers = {
        "search/users": [{**user, "permalink": "forkingandcountry", "permalink_url": "https://soundcloud.com/forkingandcountry",
                          "followers_count": 24335, "track_count": 203}],
        "search/albums": [{"id": 7, "title": "the most beautiful colours", "set_type": "ep", "track_count": 10,
                           "permalink_url": "https://soundcloud.com/forkingandcountry/sets/colours", "user": user,
                           "artwork_url": "https://i1.sndcdn.com/artworks-colours-large.jpg", "release_date": "2026-09-18T00:00:00Z"}],
        "search/playlists_without_albums": [{"id": 8, "title": "Best of", "set_type": "", "track_count": 24,
                                             "permalink_url": "https://soundcloud.com/dava/sets/best-of", "user": {"username": "Dava"},
                                             "artwork_url": None, "tracks": [{"artwork_url": "https://i1.sndcdn.com/artworks-first-large.jpg"}]}],
        "search/tracks": [{"id": 9, "title": "TOGETHER", "duration": 206_000, "playback_count": 200_100,
                           "display_date": "2020-05-01T00:00:00Z", "permalink_url": "https://soundcloud.com/forkingandcountry/together",
                           "artwork_url": "https://i1.sndcdn.com/artworks-together-large.png", "user": user}],
    }

    answer = YtDlpSource().search(SOUNDCLOUD, "for king and country")

    assert answer.notice is None
    assert [call[1] for call in api.calls] == [{"q": "for king and country", "limit": limit} for limit in (5, 5, 5, 20)]
    assert [(r.kind, r.kind_label, r.title, r.author_name, r.url, r.image_url, r.facts) for r in answer.results] == [
        (LinkKind.COLLECTION, "Account", "for KING & COUNTRY", None, "https://soundcloud.com/forkingandcountry",
         "https://i1.sndcdn.com/avatars-fkac-t500x500.jpg", ("24.3K followers", "203 tracks")),
        (LinkKind.COLLECTION, "EP", "the most beautiful colours", "for KING & COUNTRY", "https://soundcloud.com/forkingandcountry/sets/colours",
         "https://i1.sndcdn.com/artworks-colours-t500x500.jpg", ("10 tracks", "18 Sep 2026")),
        (LinkKind.COLLECTION, "Playlist", "Best of", "Dava", "https://soundcloud.com/dava/sets/best-of",
         "https://i1.sndcdn.com/artworks-first-t500x500.jpg", ("24 tracks",)),
        (LinkKind.VIDEO, "Track", "TOGETHER", "for KING & COUNTRY", "https://soundcloud.com/forkingandcountry/together",
         "https://i1.sndcdn.com/artworks-together-t500x500.png", ("3:26", "1 May 2020", "200.1K plays")),
    ]


def test_when_soundclouds_search_fails_the_track_search_answers_and_says_so(searches):
    answer = YtDlpSource().search(SOUNDCLOUD, "for king and country")
    results = answer.results

    assert (answer.notice.badge, answer.notice.tone) == ("Tracks only", "warning")

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
    assert implementation.creator_root(page) == "https://soundcloud.com/forkingandcountry"


def test_a_share_link_that_leads_off_soundcloud_is_left_as_it_is(monkeypatch):
    monkeypatch.setattr(other_sites.requests, "head", lambda url, **kwargs: _Redirect("https://example.com/elsewhere"))
    site = sites.site_for(SHARE_LINK)

    assert IMPLEMENTATIONS[site.key](site, runner.run_json).full_link(SHARE_LINK) == SHARE_LINK
