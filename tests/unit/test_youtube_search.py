"""Search YouTube: the API while the search share has room, yt-dlp otherwise, and a notice saying which answered."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sources import LinkKind
from sources.ytdlp import YtDlpSource
from sources.ytdlp.youtube_api import Share, key as key_store, quota

from test_youtube_api import quota_settings  # noqa: F401
from test_youtube_catalogue import _video_item, lookups, youtube, ytdlp_dir  # noqa: F401

RECORDED = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "youtube-search" / "veritasium.json").read_text())
CHANNELS = ("--flat-playlist", "--playlist-items", "1:5",
            "https://www.youtube.com/results?search_query=veritasium&sp=EgIQAg%253D%253D")
PLAYLISTS = ("--flat-playlist", "--playlist-items", "1:5",
             "https://www.youtube.com/results?search_query=veritasium&sp=EgIQAw%253D%253D")
VIDEOS = ("--flat-playlist", "ytsearch20:veritasium")


@pytest.fixture
def recorded(lookups):
    answers, calls = lookups
    answers[CHANNELS] = RECORDED["channels"]
    answers[PLAYLISTS] = RECORDED["playlists"]
    answers[VIDEOS] = RECORDED["videos"]
    return calls


def _search_item(kind: str, value: str, title: str) -> dict:
    return {
        "id": {"kind": f"youtube#{kind}", f"{kind}Id": value},
        "snippet": {"title": title, "channelTitle": "Veritasium", "description": f"About {title}",
                    "publishedAt": "2026-10-18T15:00:00Z",
                    "thumbnails": {"high": {"url": f"https://i.ytimg.com/{value}.jpg"}}},
    }


def test_with_a_key_the_api_answers_with_counts_durations_and_dates(youtube):
    youtube.channels["UCv"] = {"id": "UCv", "handle": "@veritasium", "snippet": {"title": "Veritasium"},
                               "statistics": {"subscriberCount": "18100000", "videoCount": "412"}}
    youtube.playlist_details["PL1"] = {"id": "PL1", "contentDetails": {"itemCount": 38}}
    youtube.videos["v1"] = _video_item("v1", duration="PT19M5S", published="2026-10-18T15:00:00Z")
    youtube.search_results = [
        _search_item("channel", "UCv", "Veritasium"), _search_item("playlist", "PL1", "Physics favourites"),
        _search_item("video", "v1", "Why no one has measured the speed of light"),
    ]

    answer = YtDlpSource().search("veritasium")

    channel, playlist, video = answer.results
    assert (channel.kind, channel.slug, channel.kind_label, channel.facts) == (
        LinkKind.SHOW, "UCv", "Channel", ("18.1M subscribers", "412 videos"))
    assert channel.url == "https://www.youtube.com/channel/UCv"
    assert (playlist.kind_label, playlist.url, playlist.facts) == (
        "Playlist", "https://www.youtube.com/playlist?list=PL1", ("38 videos",))
    assert (video.kind, video.facts) == (LinkKind.VIDEO, ("19:05", "18 Oct 2026"))
    # 100 units for the search and one for each kind of details, all from the search share.
    assert quota.status().usage(Share.SEARCH).used == 103
    assert answer.notice.badge == "Search via YouTube API" and answer.notice.tone == "neutral"
    assert answer.notice.text == "About 18 API searches left today"


def test_the_same_search_within_an_hour_costs_nothing(youtube):
    source = YtDlpSource()
    source.search("veritasium")
    source.search("  Veritasium ")

    assert [name for name, _ in youtube.calls] == ["search"]


def test_without_a_key_ytdlp_answers_with_channels_playlists_and_videos(recorded):
    answer = YtDlpSource().search("veritasium")

    assert [(r.kind_label, r.title) for r in answer.results] == [
        ("Channel", "Veritasium"), ("Channel", "2veritasium"),
        ("Playlist", "Fascinating Stories"), ("Playlist", "Veritasium - Nuclear Engineer Reacts"),
        ("Video", "No device could prove Einstein wrong... until now"), ("Video", "The Insane Engineering of Fiber Optics"),
    ]
    channel, video = answer.results[0], answer.results[4]
    assert channel.slug == "UCHnyfMqiRRG1u-2MsSQLbXA" and channel.facts == ("21.4M subscribers",)
    assert channel.image_url.startswith("https://yt3.ggpht.com/")
    assert (video.slug, video.author_name, video.facts) == ("eyZEqSPeMwg", "Veritasium", ("34:28",))
    assert answer.results[2].author_name == "Veritasium"
    assert answer.notice.badge == "Search via yt-dlp" and answer.notice.link_path == "/settings?tab=sources"


def test_with_the_search_quota_used_up_ytdlp_answers_with_a_warning(youtube, recorded):
    quota.mark_exhausted()

    answer = YtDlpSource().search("veritasium")

    assert len(answer.results) == 6
    assert (answer.notice.badge, answer.notice.tone) == ("Slower search via yt-dlp", "warning")
    assert "used up" in answer.notice.text
    assert youtube.calls == []


def test_with_a_search_share_of_zero_ytdlp_answers_and_says_why(youtube, recorded, quota_settings):
    quota_settings(search_quota=0)

    answer = YtDlpSource().search("veritasium")

    assert len(answer.results) == 6 and "turned off" in answer.notice.text
    assert youtube.calls == []


def test_when_the_api_fails_ytdlp_answers(youtube, recorded):
    youtube.failing.add("search")

    answer = YtDlpSource().search("veritasium")

    assert len(answer.results) == 6 and answer.notice.tone == "warning"


def test_failed_channel_and_playlist_searches_still_leave_the_videos(lookups):
    answers, _ = lookups
    answers[VIDEOS] = RECORDED["videos"]

    answer = YtDlpSource().search("veritasium")

    assert [r.kind_label for r in answer.results] == ["Video", "Video"]
