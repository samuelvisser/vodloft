"""Each Site says what a Local Media Profile can download from it; other Sites offer the defaults."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from sources import DownloadOptions, VIDEO_HEIGHTS, get_source, site_for


def _collection_profile(preferred_format, source_keys=None):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    return CollectionLocalMediaProfileAPICreate(
        name="Profile", type="collection", preferred_format=preferred_format, source_keys=source_keys,
        output_template="/downloads/shows/{{ collection }}/{{ episode }}.ext",
    )


def test_only_the_daily_wire_keeps_an_hls_bundle_and_has_fixed_versions():
    dailywire = get_source("dailywire").download_options
    assert dailywire == DownloadOptions(video_heights=(480, 720, 1080), hls_bundle=True, quality_choices=False)
    # yt-dlp names no Sites, so every site it downloads from offers the defaults.
    assert get_source("ytdlp").download_options == DownloadOptions()
    assert site_for("https://www.youtube.com/@channel", "ytdlp").downloads == DownloadOptions()
    assert DownloadOptions().video_heights == VIDEO_HEIGHTS and not DownloadOptions().hls_bundle


def test_a_profile_offers_what_any_of_its_sources_offers():
    assert _collection_profile("format_hls").preferred_format == "format_hls"
    with pytest.raises(ValidationError, match="None of this profile's Sources can download an HLS bundle"):
        _collection_profile("format_hls", ["ytdlp"])
    with pytest.raises(ValidationError, match="can download 4K"):
        _collection_profile("format_4k", ["dailywire"])
    assert _collection_profile("format_720p", ["dailywire"]).preferred_format == "format_720p"
    assert _collection_profile("format_4k", ["ytdlp"]).preferred_format == "format_4k"


def test_each_site_downloads_the_nearest_it_has():
    from backend.services.local_media_profile_sources import format_for_site

    youtube = site_for("https://www.youtube.com/@channel", "ytdlp")
    dailywire = site_for("https://www.dailywire.com/show/a", "dailywire")
    # The HLS bundle tops out at 1080p, so a site without one downloads that.
    assert format_for_site(youtube, "format_hls") == "format_1080p"
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
    assert read["downloadOptions"] == {"videoHeights": [480, 720, 1080], "audioOnly": True, "hlsBundle": True, "qualityChoices": False}
