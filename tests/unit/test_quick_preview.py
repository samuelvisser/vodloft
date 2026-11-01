"""A link's title and thumbnail first, while the full Quick download lookup runs."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from backend.security.access import TEMPLATES, Access, SourceLimit


def _ytdlp():
    from sources.ytdlp.source import YtDlpSource

    return YtDlpSource()


class _Response:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._data


def test_youtube_videos_preview_through_oembed(monkeypatch):
    from sources.ytdlp import source as module

    asked = []

    def fake_get(url, params, timeout):
        asked.append(params["url"])
        return _Response({"title": "A video", "author_name": "A channel", "thumbnail_url": "https://i.ytimg.com/x.jpg"})

    monkeypatch.setattr(module.requests, "get", fake_get)
    preview = _ytdlp().preview("https://youtu.be/abc")
    assert (preview.title, preview.author_name, preview.image_url, preview.site) == (
        "A video", "A channel", "https://i.ytimg.com/x.jpg", "YouTube",
    )
    assert asked == ["https://youtu.be/abc"]


def test_other_links_and_failures_have_no_preview(monkeypatch):
    from sources.ytdlp import source as module

    def failing_get(url, params, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(module.requests, "get", failing_get)
    source = _ytdlp()
    assert source.preview("https://youtu.be/abc") is None
    assert source.preview("https://vimeo.com/1") is None
    # Channels and playlists are shows, not a single video.
    assert source.preview("https://www.youtube.com/@channel") is None
    assert source.preview("https://www.youtube.com/playlist?list=PL1") is None


def test_a_link_already_looked_up_previews_from_that_lookup(monkeypatch):
    from sources.ytdlp import source as module

    monkeypatch.setattr(module.requests, "get", lambda *a, **k: pytest.fail("no request expected"))
    source = _ytdlp()
    source._cache["https://vimeo.com/1"] = (module.time.monotonic(), {
        "title": "Cached", "uploader": "Someone", "extractor_key": "Vimeo", "thumbnail": "https://x/t.jpg",
    })
    assert source.preview("https://vimeo.com/1").title == "Cached"


def _limited(domains):
    return Access.for_user(
        user_id=7, username="tim", levels=TEMPLATES["downloader"].levels,
        source_limits={"ytdlp": SourceLimit("ytdlp", domains)}, members_only=False, delete_files=False,
        must_change_password=False, template_key="downloader", session_version=1,
    )


def test_the_preview_respects_domain_limits(monkeypatch):
    from backend.api.endpoints.quick_downloads import service
    from backend.api.models.quick_download import QuickDownloadOptionsAPIRequest
    from sources.ytdlp import source as module

    monkeypatch.setattr(service, "preferred_sources", lambda s: {})
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: _Response({"title": "A video"}))
    body = QuickDownloadOptionsAPIRequest(url="https://youtu.be/abc")
    assert service.quick_download_preview(None, _limited(("youtu.be",)), body).title == "A video"
    assert service.quick_download_preview(None, _limited(("vimeo.com",)), body) is None
    assert service.quick_download_preview(None, Access.full(), body).source_key == "ytdlp"
