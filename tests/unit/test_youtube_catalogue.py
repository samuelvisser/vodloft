"""YouTube shows listed through the Data API, and the same shows without a key."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sources import LinkKind, MAIN_TAG
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource
from sources.ytdlp.youtube_api import Share, client as client_module, key as key_store, mapping, quota

FIXTURES = sorted((Path(__file__).resolve().parents[1] / "fixtures" / "youtube").glob("*.json"))


@pytest.fixture(autouse=True)
def ytdlp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ytdlp_directory", lambda: tmp_path / "yt-dlp")
    monkeypatch.setattr(client_module.pacing, "pause", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("sources.ytdlp.source._LISTING_PAUSE_SECONDS", 0)


@pytest.fixture
def lookups(monkeypatch):
    answers: dict[tuple[str, ...], dict] = {}
    calls: list[tuple[str, ...]] = []

    def run_json(*args):
        calls.append(args)
        if args not in answers:
            raise runner.YtDlpError("Video unavailable")
        return answers[args]

    monkeypatch.setattr(runner, "run_json", run_json)
    return answers, calls


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.ok = status < 400
        self._body = body

    def json(self):
        return self._body


def _video_item(video_id: str, *, channel: str = "UC1", published: str = "2024-03-01T10:00:00Z",
                duration: str = "PT10M", live: dict | None = None, broadcast: str = "none") -> dict:
    item = {
        "id": video_id,
        "snippet": {
            "publishedAt": published, "channelId": channel, "channelTitle": "A Channel", "title": f"Video {video_id}",
            "description": f"About {video_id}", "liveBroadcastContent": broadcast,
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        },
        "contentDetails": {"duration": duration},
    }
    if live is not None:
        item["liveStreamingDetails"] = live
    return item


class FakeYouTube:
    """Answers the Data API like YouTube would, from playlists and videos it is given."""

    def __init__(self):
        self.playlists: dict[str, list[str]] = {}
        self.videos: dict[str, dict] = {}
        self.channels: dict[str, dict] = {}
        self.failing: set[str] = set()
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, params))
        if endpoint in self.failing:
            return FakeResponse(503, {"error": {"errors": [{"reason": "backendError"}]}})
        if endpoint == "channels":
            items = [c for c in self.channels.values() if params.get("forHandle") in (None, c["handle"])]
            if "id" in params:
                items = [c for c in items if c["id"] in params["id"].split(",")]
            return FakeResponse(200, {"items": [{"id": c["id"], "snippet": c["snippet"]} for c in items]})
        if endpoint == "playlistItems":
            if params["playlistId"] not in self.playlists:
                return FakeResponse(404, {"error": {"errors": [{"reason": "playlistNotFound"}]}})
            ids = self.playlists[params["playlistId"]]
            start = int(params.get("pageToken") or 0)
            page = {"items": [{"contentDetails": {"videoId": video_id}} for video_id in ids[start:start + 50]]}
            if start + 50 < len(ids):
                page["nextPageToken"] = str(start + 50)
            return FakeResponse(200, page)
        if endpoint == "videos":
            return FakeResponse(200, {"items": [self.videos[i] for i in params["id"].split(",") if i in self.videos]})
        raise AssertionError(f"Unexpected call to {endpoint}")


@pytest.fixture
def youtube(monkeypatch):
    fake = FakeYouTube()
    fake.channels["UC1"] = {"id": "UC1", "handle": "@a-channel", "snippet": {
        "title": "A Channel", "description": "All about A",
        "thumbnails": {"high": {"url": "https://yt3.example/a.jpg"}},
    }}
    monkeypatch.setattr(client_module.requests, "Session", lambda: fake)
    key_store.save("AIzaTEST")
    return fake


def _calls(fake: FakeYouTube, endpoint: str) -> int:
    return sum(1 for name, _ in fake.calls if name == endpoint)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_the_api_and_ytdlp_make_the_same_episode(path):
    """The parity rule, on real videos recorded through both: same date, tag, title and thumbnail."""
    fixture = json.loads(path.read_text())
    ytdlp_info, api_item = fixture["ytdlp"], fixture["api"]
    if "_error" in ytdlp_info:
        # yt-dlp cannot look up a livestream that has not started; the API says it is still to come.
        assert mapping.is_pending(api_item)
        return
    url = ytdlp_info["webpage_url"]
    from_ytdlp = YtDlpSource._video(ytdlp_info, url)
    from_api = mapping.video(api_item, short=fixture["playlist"] == "UUSH")

    assert from_api.published_at == from_ytdlp.published_at
    assert from_api.tag == from_ytdlp.tag
    assert (from_api.slug, from_api.url, from_api.title, from_api.author_name) == (
        from_ytdlp.slug, from_ytdlp.url, from_ytdlp.title, from_ytdlp.author_name,
    )
    # The recording keeps yt-dlp's first 300 characters of the description.
    assert from_api.description.startswith(from_ytdlp.description)
    # The API rounds up to the next second, yt-dlp down.
    assert 0 <= from_api.duration - from_ytdlp.duration <= 1
    # yt-dlp sometimes picks the WebP copy of the same picture.
    assert f"/{from_api.slug}/maxresdefault." in from_api.image_url
    assert f"/{from_api.slug}/maxresdefault." in from_ytdlp.image_url
    assert not mapping.is_pending(api_item)


def test_shorts_tabs_and_playlists_in_links():
    assert mapping.youtube_ref("https://www.youtube.com/@a-channel/videos") == mapping.YouTubeRef("handle", "@a-channel")
    assert mapping.youtube_ref("https://m.youtube.com/@caf%C3%A9/shorts") == mapping.YouTubeRef("handle", "@café", "shorts")
    assert mapping.youtube_ref("https://www.youtube.com/channel/UC1/streams").uploads_playlist("UC1") == "UULV1"
    assert mapping.youtube_ref("https://www.youtube.com/channel/UC1").uploads_playlist("UC1") == "UU1"
    assert mapping.youtube_ref("https://www.youtube.com/user/old") == mapping.YouTubeRef("username", "old")
    assert mapping.youtube_ref("https://www.youtube.com/c/Custom").kind == "custom"
    assert mapping.youtube_ref("https://www.youtube.com/playlist?list=PL9") == mapping.YouTubeRef("playlist", "PL9")
    assert mapping.youtube_ref("https://www.youtube.com/watch?v=abc") is None
    assert mapping.youtube_ref("https://www.youtube.com/@a-channel/community") is None
    assert mapping.youtube_ref("https://vimeo.com/channels/a") is None
    assert mapping.duration("PT1H2M3S") == 3723 and mapping.duration("P1DT1S") == 86401 and mapping.duration("P0D") is None


def test_a_channel_is_listed_through_the_api_with_its_shorts_and_livestreams(youtube):
    youtube.playlists["UU1"] = ["live1", "short1", "long-short", "v2", "upcoming", "gone", "v1"]
    youtube.playlists["UUSH1"] = ["short1"]
    youtube.videos.update({
        "v1": _video_item("v1", published="2023-12-31T23:30:00Z"),
        "v2": _video_item("v2", duration="PT59S"),
        "short1": _video_item("short1", duration="PT45S"),
        "long-short": _video_item("long-short", duration="PT20M"),
        "live1": _video_item("live1", published="2024-05-01T12:00:00Z", duration="PT2H",
                             live={"actualStartTime": "2024-05-01T10:00:00Z"}),
        "upcoming": _video_item("upcoming", duration="P0D", live={"scheduledStartTime": "2030-01-01T00:00:00Z"},
                                broadcast="upcoming"),
    })

    found = list(YtDlpSource().list_episodes("https://www.youtube.com/@a-channel/videos", known=frozenset()))

    # A deleted video is missing from the answer and an upcoming one waits until it has been broadcast.
    assert [(video.slug, video.tag) for video in found] == [
        ("live1", "livestream"), ("short1", "short"), ("long-short", MAIN_TAG), ("v2", MAIN_TAG), ("v1", MAIN_TAG),
    ]
    live = found[0]
    assert (live.published_at.isoformat(), live.duration) == ("2024-05-01T10:00:00+00:00", 7200.0)
    assert found[-1].published_at.year == 2023
    # One handle lookup, one uploads page, one Shorts page and one batch of details.
    assert [name for name, _ in youtube.calls] == ["channels", "playlistItems", "videos", "playlistItems"]
    # A first index is paid from the units kept free for adding shows.
    status = quota.status()
    assert (status.usage(Share.RESERVE).used, status.usage(Share.CHECKS).used) == (4, 0)


def test_a_rescan_only_details_new_videos_and_pays_from_the_checks_share(youtube):
    youtube.playlists["UU1"] = [f"v{n}" for n in range(120)]
    youtube.videos.update({f"v{n}": _video_item(f"v{n}") for n in range(120)})

    found = list(YtDlpSource().list_episodes(
        "https://www.youtube.com/channel/UC1/videos", known=frozenset(f"v{n}" for n in range(3, 120)),
    ))

    assert [video.slug for video in found] == ["v0", "v1", "v2"]
    # Three pages of IDs, one batch of details, and no Shorts lookup for long videos.
    assert (_calls(youtube, "channels"), _calls(youtube, "playlistItems"), _calls(youtube, "videos")) == (0, 3, 1)
    assert quota.status().usage(Share.CHECKS).used == 4


def test_adding_a_show_moves_on_to_the_checks_share_when_the_reserve_is_used(youtube):
    youtube.playlists["PL1"] = ["v1"]
    youtube.videos["v1"] = _video_item("v1")
    assert quota.try_spend(Share.RESERVE, quota.status().usage(Share.RESERVE).limit)

    found = list(YtDlpSource().list_episodes("https://www.youtube.com/playlist?list=PL1", known=frozenset()))

    assert [video.slug for video in found] == ["v1"]
    assert quota.status().usage(Share.CHECKS).used == 2


def test_a_failing_batch_falls_back_to_ytdlp_for_those_videos_only(youtube, lookups):
    answers, calls = lookups
    youtube.playlists["PL1"] = ["v1"]
    youtube.failing.add("videos")
    answers[("--no-playlist", "https://www.youtube.com/watch?v=v1")] = {
        "id": "v1", "extractor_key": "Youtube", "title": "From yt-dlp", "upload_date": "20240102",
        "webpage_url": "https://www.youtube.com/watch?v=v1", "media_type": "video",
    }

    found = list(YtDlpSource().list_episodes("https://www.youtube.com/playlist?list=PL1", known=frozenset()))

    assert [(video.slug, video.title) for video in found] == [("v1", "From yt-dlp")]
    assert [args[0] for args in calls] == ["--no-playlist"]


def test_without_the_api_a_channel_lists_its_videos_shorts_and_live_tabs(lookups):
    answers, calls = lookups
    base = "https://www.youtube.com/@a-channel"
    for tab, slug in (("videos", "v1"), ("streams", "l1")):
        answers[("--flat-playlist", f"{base}/{tab}")] = {"_type": "playlist", "entries": [
            {"id": slug, "ie_key": "Youtube", "url": f"https://www.youtube.com/watch?v={slug}"},
        ]}
    for slug, info in (
        ("v1", {"media_type": "video", "live_status": "not_live"}),
        ("l1", {"media_type": "livestream", "live_status": "is_live"}),
    ):
        answers[("--no-playlist", f"https://www.youtube.com/watch?v={slug}")] = {
            "id": slug, "extractor_key": "Youtube", "title": slug, "upload_date": "20240102",
            "webpage_url": f"https://www.youtube.com/watch?v={slug}", **info,
        }

    found = list(YtDlpSource().list_episodes(f"{base}/videos", known=frozenset()))

    # The channel has no Shorts tab, and its livestream is still live.
    assert [video.slug for video in found] == ["v1"]
    assert [args[-1] for args in calls if args[0] == "--flat-playlist"] == [
        f"{base}/videos", f"{base}/shorts", f"{base}/streams",
    ]


def test_a_channel_link_is_resolved_through_the_api(youtube, lookups):
    _, calls = lookups
    source = YtDlpSource()

    link = source.resolve("https://www.youtube.com/@a-channel")
    details = source.show_details("https://www.youtube.com/@a-channel")

    assert (link.kind, link.slug, link.url, link.title, link.site) == (
        LinkKind.SHOW, "UC1", "https://www.youtube.com/@a-channel/videos", "A Channel", "YouTube",
    )
    assert (details.slug, details.description, details.image_url, details.author_url) == (
        "UC1", "All about A", "https://yt3.example/a.jpg", "https://www.youtube.com/channel/UC1",
    )
    assert calls == []
    assert quota.status().usage(Share.RESERVE).used == 2


def test_an_unknown_channel_is_left_to_ytdlp(youtube, lookups):
    answers, calls = lookups
    tab = "https://www.youtube.com/@nobody/videos"
    answers[("--no-playlist", "--flat-playlist", "--playlist-items", "1", tab)] = {
        "_type": "playlist", "id": "UC9", "channel_id": "UC9", "channel": "Nobody", "title": "Nobody - Videos",
        "extractor_key": "YoutubeTab",
    }
    assert YtDlpSource().resolve(tab).slug == "UC9"
    assert len(calls) == 1
