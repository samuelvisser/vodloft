"""Patreon posts for patrons only are kept as locked episodes, not dropped, so a collection of a paid Patreon finds them."""
from __future__ import annotations

import pytest

from sources import ItemRef
from sources.ytdlp import sites
from sources import ytdlp_runner as runner
from sources.ytdlp import YtDlpSource

CAMPAIGN = "https://www.patreon.com/creator"
NO_ACCESS = "You do not have access to this post"
NO_MEDIA = "No supported media found in this post"


def _post_url(post_id: str) -> str:
    return f"https://www.patreon.com/posts/{post_id}"


def _post(post_id: str, **fields) -> dict:
    return {
        "id": post_id, "extractor_key": "Patreon", "title": f"Post {post_id}", "webpage_url": _post_url(post_id),
        "upload_date": "20261120", **fields,
    }


@pytest.fixture
def patreon(monkeypatch):
    """A campaign of an open video, a post for patrons only and a text post, as yt-dlp answers without cookies."""
    refused = {"open": None, "paid": NO_ACCESS, "text": NO_MEDIA}

    def run_json(*args, **_kwargs):
        url = args[-1]
        if url == CAMPAIGN:
            return {"_type": "playlist", "id": "1", "entries": [
                {"_type": "url", "id": post_id, "url": _post_url(post_id), "ie_key": "Patreon"} for post_id in refused
            ]}
        post_id = url.rsplit("/", 1)[-1]
        if refused[post_id] and "--ignore-no-formats-error" not in args:
            raise runner.YtDlpError(f"[patreon] {post_id}: {refused[post_id]}")
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


def test_a_post_for_patrons_only_is_listed_locked_and_a_text_post_is_left_out(patreon):
    found = {video.title: video for video in YtDlpSource().list_episodes(CAMPAIGN, known=frozenset())}

    assert set(found) == {"Post open", "Post paid"}
    assert found["Post open"].access is None
    assert found["Post paid"].access == sites.MEMBERS_KEY


def test_a_post_for_patrons_only_is_looked_up_locked_on_its_own(patreon):
    refresh = YtDlpSource().check_pending([ItemRef("paid", _post_url("paid")), ItemRef("text", _post_url("text"))])

    assert set(refresh.details) == {"paid"}
    assert refresh.details["paid"].access == sites.MEMBERS_KEY
    assert not refresh.removed


def test_patreon_calls_its_locked_posts_patrons_only():
    access = sites.site_for(CAMPAIGN).access(sites.MEMBERS_KEY)
    assert access.label == "Patrons only"
