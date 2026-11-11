"""Each Site says what a Local Media Profile can download from it; other Sites offer the defaults."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from sources import DownloadOptions, VIDEO_HEIGHTS, get_source, site_for


def _collection_profile(preferred_format, site_keys=None, include_upcoming_sites=True):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    return CollectionLocalMediaProfileAPICreate(
        name="Profile", type="collection", preferred_format=preferred_format, site_keys=site_keys,
        include_upcoming_sites=include_upcoming_sites,
        output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
    )


def test_the_daily_wire_and_youtube_keep_an_hls_bundle():
    dailywire = get_source("dailywire").download_options
    assert dailywire == DownloadOptions(video_heights=(480, 720, 1080), hls_heights=(480, 720, 1080), subtitles=True)
    assert dailywire.hls_bundle and not dailywire.quality_choices
    # yt-dlp offers what any of its sites offers: the quality choices and subtitles on every site, and
    # YouTube's HLS bundle.
    youtube = DownloadOptions(hls_heights=(360, 720, 1080), subtitles=True, quality_choices=True)
    assert get_source("ytdlp").download_options == youtube
    assert site_for("https://www.youtube.com/@channel", "ytdlp").downloads == youtube
    assert site_for("https://vimeo.com/channel", "ytdlp").downloads == DownloadOptions(subtitles=True, quality_choices=True)
    # NPO Start downloads with yt-dlp too, so it has the quality choices, but it has no subtitles.
    assert get_source("npo").download_options == DownloadOptions(quality_choices=True)
    # A Site has nothing to choose unless its contract says so.
    assert DownloadOptions().video_heights == VIDEO_HEIGHTS and not DownloadOptions().hls_bundle
    assert not DownloadOptions().quality_choices and not DownloadOptions().subtitles


def test_a_site_still_to_come_has_what_a_source_that_fetches_any_site_offers():
    from backend.services.local_media_profile_sites import profile_download_options

    assert profile_download_options("collection", ["dailywire"], False).quality_choices is False
    assert profile_download_options("collection", ["dailywire"], True).quality_choices is True
    assert profile_download_options("collection", ["npo"], False).subtitles is False
    assert profile_download_options("collection", ["npo"], True).subtitles is True


def test_a_profile_offers_what_any_of_its_sites_offers():
    assert _collection_profile("format_hls").preferred_format == "format_hls"
    assert _collection_profile("format_hls", ["youtube"], False).preferred_format == "format_hls"
    with pytest.raises(ValidationError, match="None of this profile's Sites can download an HLS bundle"):
        _collection_profile("format_hls", ["npo"], False)
    with pytest.raises(ValidationError, match="can download 4K"):
        _collection_profile("format_4k", ["dailywire"], False)
    assert _collection_profile("format_720p", ["dailywire"], False).preferred_format == "format_720p"
    # Upcoming Sites offer the defaults, 4K included.
    assert _collection_profile("format_4k", ["dailywire"]).preferred_format == "format_4k"
    assert _collection_profile("format_4k", ["youtube"], False).preferred_format == "format_4k"


def test_each_site_downloads_the_nearest_it_has():
    from backend.services.local_media_profile_sites import format_for_site

    youtube = site_for("https://www.youtube.com/@channel", "ytdlp")
    dailywire = site_for("https://www.dailywire.com/show/a", "dailywire")
    vimeo = site_for("https://vimeo.com/channel", "ytdlp")
    # The HLS bundle tops out at 1080p, so a site without one downloads that.
    assert format_for_site(vimeo, "format_hls") == "format_1080p"
    assert format_for_site(youtube, "format_hls") == "format_hls"
    assert format_for_site(youtube, "format_4k") == "format_4k"
    assert format_for_site(youtube, "format_audio_only") == "format_audio_only"
    assert format_for_site(dailywire, "format_hls") == "format_hls"
    assert format_for_site(dailywire, "format_4k") == "format_1080p"
    assert format_for_site(dailywire, "format_360p") == "format_480p"


def test_a_feed_only_prefers_resolutions_its_site_has():
    from backend.api.endpoints.rss_stream_profiles.service import ensure_site_can_stream

    dailywire = SimpleNamespace(sharing_url="https://www.dailywire.com/show/heights", source_key="dailywire")
    with pytest.raises(HTTPException, match="has no 4k video"):
        ensure_site_can_stream(
            dailywire, use_source_stream=False, stream_live_episodes=False, preferred_format="format_4k", video_output_mode="mp4",
        )
    ensure_site_can_stream(
        dailywire, use_source_stream=True, stream_live_episodes=False, preferred_format="format_1080p", video_output_mode="mp4",
    )


def test_sources_say_what_they_can_download():
    from backend.api.models.source import SourceAPIRead

    read = SourceAPIRead.model_validate(get_source("dailywire")).model_dump(by_alias=True)
    assert read["downloadOptions"] == {
        "videoHeights": [480, 720, 1080], "audioOnly": True, "hlsBundle": True, "hlsHeights": [480, 720, 1080],
        "subtitles": True, "qualityChoices": False,
    }
