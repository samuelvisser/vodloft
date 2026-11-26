"""The Sites VODLoft searches through their own public search APIs: Dailymotion, Kick, Nebula, Odysee, PeerTube and
Niconico, each answered here with a recorded answer of its API."""
from __future__ import annotations

import pytest

from sources import LinkKind
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource, site_search
from sources.ytdlp.sites import site_of


@pytest.fixture
def answers(monkeypatch):
    """What each API answers, by the address asked; every request is kept in ``asked``."""
    recorded: dict[str, object] = {}
    asked: list[tuple[str, dict | None, dict | None]] = []

    def ask(site_name, url, *, params=None, body=None):
        asked.append((url, params, body))
        key = f"{url}#{(params or {}).get('claimType', '')}"
        return recorded[key] if key in recorded else recorded[url]

    monkeypatch.setattr(site_search, "ask", ask)
    recorded["asked"] = asked
    return recorded


def _search(key: str, query: str = "query"):
    return YtDlpSource().search(site_of(key), query).results


def test_every_site_with_its_own_search_api_is_searchable_and_some_say_what_they_miss():
    keys = {site.key: site for site in YtDlpSource().search_sites}
    assert {"dailymotion", "kick", "nebula", "lbry", "peertube", "niconico"} <= set(keys)
    assert keys["lbry"].name == "Odysee"
    # Each search costs nothing, so the search page searches while the user types.
    assert not any(keys[key].costly_search for key in ("dailymotion", "kick", "nebula", "lbry", "peertube", "niconico"))
    assert keys["nebula"].search_note is None
    assert "only finds channels" in keys["kick"].search_note and "only finds channels" in keys["twitch"].search_note
    assert keys["youtube"].search_note is None and keys["soundcloud"].search_note is None


def test_dailymotion_finds_channels_with_videos_then_videos(answers):
    answers["https://api.dailymotion.com/users"] = {"list": [
        {"username": "france24", "screenname": "FRANCE 24", "url": "https://www.dailymotion.com/france24",
         "description": "Info<br />24/7", "avatar_360_url": "https://s1.dmcdn.net/u/a/360x360", "videos_total": 50652,
         "followers_total": 8720},
        {"username": "empty", "screenname": "Nothing yet", "videos_total": 0},
    ]}
    answers["https://api.dailymotion.com/videos"] = {"list": [
        {"id": "x8zhrsm", "title": "Lofi", "url": "https://www.dailymotion.com/video/x8zhrsm", "duration": 125,
         "created_time": 1717299864, "views_total": 157, "owner.screenname": "Animity"},
    ]}
    channel, video = _search("dailymotion")
    assert (channel.kind, channel.slug, channel.title, channel.description) == (LinkKind.COLLECTION, "france24", "FRANCE 24", "Info\n24/7")
    assert channel.facts == ("8.7K followers", "50.7K videos")
    assert (video.kind, video.url, video.author_name, video.facts) == (
        LinkKind.VIDEO, "https://www.dailymotion.com/video/x8zhrsm", "Animity", ("2:05", "2 Jun 2024", "157 views"),
    )


def test_kick_finds_channels_by_their_videos(answers):
    answers["https://kick.com/api/search"] = {"channels": [
        {"slug": "xqc", "isLive": True, "followers_count": 1864957,
         "user": {"username": "xQc", "bio": "Juicer", "profilePic": "https://files.kick.com/xqc.webp"}},
        {"slug": "banned", "is_banned": True, "user": {"username": "Banned"}},
    ], "livestreams": {"tags": []}}
    [channel] = _search("kick")
    # The channel's own page is its live stream, which yt-dlp only reads while it is live.
    assert channel.url == "https://kick.com/xqc/videos"
    assert (channel.title, channel.facts) == ("xQc", ("Live now", "1.9M followers"))


def test_nebula_finds_channels_then_videos(answers):
    answers["https://content.api.nebula.app/video_channels/search/"] = {"results": [
        {"slug": "wendover", "title": "Wendover", "genre_category_title": "Culture",
         "images": {"avatar": {"src": "https://images.nebula.tv/avatar"}}},
    ]}
    answers["https://content.api.nebula.app/video_episodes/search/"] = {"results": [
        {"slug": "wendover-the-nfls-concussion-problem", "title": "The NFL's Concussion Problem", "duration": 1197,
         "published_at": "2025-11-20T15:00:00Z", "channel_title": "Wendover",
         "share_url": "https://nebula.tv/videos/wendover-the-nfls-concussion-problem/",
         "images": {"thumbnail": {"src": "https://images.nebula.tv/thumb"}}},
    ]}
    channel, video = _search("nebula")
    assert (channel.url, channel.image_url, channel.facts) == ("https://nebula.tv/wendover", "https://images.nebula.tv/avatar", ("Culture",))
    assert (video.url, video.author_name, video.facts) == (
        "https://nebula.tv/videos/wendover-the-nfls-concussion-problem/", "Wendover", ("19:57", "20 Nov 2025"),
    )


def test_odysee_finds_claims_and_reads_their_details_in_the_order_found(answers):
    answers["https://lighthouse.odysee.tv/search#channel"] = [{"claimId": "fb36"}]
    answers["https://lighthouse.odysee.tv/search#file"] = [{"claimId": "da20"}, {"claimId": "gone"}]
    answers["https://api.na-backend.odysee.com/api/v1/proxy"] = {"result": {"items": [
        {"claim_id": "da20", "value_type": "stream", "canonical_url": "lbry://@Qwinten#b/The-Snowflake-Myth#d",
         "value": {"title": "The Snowflake Myth", "stream_type": "video", "release_time": "1734384864",
                   "video": {"duration": 1170}, "thumbnail": {"url": "https://thumbs.odycdn.com/t.webp"}},
         "signing_channel": {"name": "@Qwinten", "value": {"title": "just a dutch dude"}}},
        {"claim_id": "fb36", "value_type": "channel", "canonical_url": "lbry://@veritasium#f", "name": "@veritasium",
         "value": {"title": "Veritasium", "thumbnail": {"url": "https://thumbnails.lbry.com/v"}},
         "meta": {"claims_in_channel": 562}},
    ]}}
    channel, video = _search("lbry")
    assert (channel.url, channel.title, channel.facts) == ("https://odysee.com/@veritasium:f", "Veritasium", ("@veritasium", "562 uploads"))
    assert (video.url, video.author_name, video.facts) == (
        "https://odysee.com/@Qwinten:b/The-Snowflake-Myth:d", "just a dutch dude", ("19:30", "16 Dec 2024"),
    )
    [*_searches, (url, _params, body)] = answers["asked"]
    assert body["params"]["claim_ids"] == ["fb36", "da20", "gone"]


def test_odysee_asks_for_no_details_when_its_search_finds_nothing(answers):
    answers["https://lighthouse.odysee.tv/search"] = []
    assert _search("lbry") == []
    assert len(answers["asked"]) == 2


def test_peertube_shows_only_what_is_on_servers_yt_dlp_reads(answers):
    answers["https://sepiasearch.org/api/v1/search/video-channels"] = {"data": [
        {"url": "https://video.blender.org/video-channels/blender_channel", "name": "blender_channel",
         "host": "video.blender.org", "displayName": "Blender", "followersCount": 1299, "videosCount": 876,
         "avatars": [{"url": "https://sepiasearch.org/small", "width": 48}, {"url": "https://sepiasearch.org/big", "width": 120}]},
        {"url": "https://unknown.example/video-channels/someone", "name": "someone", "host": "unknown.example"},
    ]}
    answers["https://sepiasearch.org/api/v1/search/video-playlists"] = {"data": [
        {"url": "https://video.blender.org/videos/watch/playlist/58ae", "shortUUID": "bX9Sa5fsbXRyMjS6R21eSW",
         "host": "video.blender.org", "displayName": "Blender Tomorrow", "videosLength": 5,
         "videoChannel": {"displayName": "Blender Developers"}},
    ]}
    answers["https://sepiasearch.org/api/v1/search/videos"] = {"data": [
        {"url": "https://video.blender.org/videos/watch/b29290cc-dc51-4a12-bcb2-2aa5fece7605", "uuid": "b292",
         "name": "OVERGROWN", "duration": 70, "publishedAt": "2026-07-10T14:00:16.560Z", "views": 12800,
         "channel": {"displayName": "Blender Studio"}},
    ]}
    channel, playlist, video = _search("peertube")
    # Channels and playlists get the addresses yt-dlp reads them by.
    assert (channel.url, channel.slug, channel.image_url) == ("https://video.blender.org/c/blender_channel", "blender_channel", "https://sepiasearch.org/big")
    assert channel.facts == ("video.blender.org", "1.3K followers", "876 videos")
    assert (playlist.url, playlist.author_name) == ("https://video.blender.org/w/p/bX9Sa5fsbXRyMjS6R21eSW", "Blender Developers")
    assert (video.title, video.facts) == ("OVERGROWN", ("1:10", "10 Jul 2026", "12.8K views"))


def test_niconico_finds_videos_and_names_itself_to_the_api(answers):
    answers["https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search"] = {"data": [
        {"contentId": "sm9", "title": "Lets Go", "lengthSeconds": 320, "startTime": "2007-03-06T00:33:00+09:00",
         "viewCounter": 22000000, "thumbnailUrl": "https://nicovideo.cdn.nimg.jp/thumbnails/9/9"},
    ]}
    [video] = _search("niconico")
    assert (video.kind, video.url, video.facts) == (
        LinkKind.VIDEO, "https://www.nicovideo.jp/watch/sm9", ("5:20", "6 Mar 2007", "22M views"),
    )
    [(_url, params, _body)] = answers["asked"]
    assert params["_context"] == "VODLoft"


def test_a_site_that_does_not_answer_says_so(monkeypatch):
    import requests

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "request", refuse)
    with pytest.raises(runner.YtDlpError, match="Nebula could not be searched: ConnectionError"):
        YtDlpSource().search(site_of("nebula"), "unreachable")
