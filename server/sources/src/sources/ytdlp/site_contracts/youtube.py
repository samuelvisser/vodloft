from dataclasses import replace
from types import MappingProxyType

from ...contract import (
    Access,
    CreatorSectionNames,
    SiteSetting,
    SiteSettings,
    StreamMethod,
    UpgradeChecks,
    UpgradeImprovement,
)
from .other_sites import CREATOR_PRESETS, MEMBERS_KEY, PREMIUM_KEY, OtherSites


class YouTube(OtherSites):
    key = "youtube"
    name = "YouTube"
    # YouTube has its 360p MP4 with sound as one file, and every other resolution as separate H.264 video and M4A
    # audio, which VODLoft lists in an HLS playlist or joins. Above 1080p, YouTube only has VP9 and AV1, which podcast
    # apps often cannot play. Its links play for any address, so apps can be sent straight to them.
    stream_methods = frozenset({StreamMethod.FILE, StreamMethod.HLS, StreamMethod.LIVE})
    stream_video_heights = (360, 720, 1080)
    stream_file_height = 360
    stream_proxy_choice = True
    # YouTube's MP4 plays at once, as its own 360p file or one VODLoft joins, so nothing waits for a download.
    video_output_help = MappingProxyType({
        "mp4_hls": "Streams video using HLS, and provides mp4 as the fallback. This ensures the podcasting app will "
                   "always play video if it supports video at all.",
    })
    # Its separate H.264 video and M4A audio can be kept as an HLS bundle.
    downloads = replace(OtherSites.downloads, hls_heights=(360, 720, 1080))
    # SponsorBlock only has YouTube's videos.
    upgrade_checks = UpgradeChecks((
        UpgradeImprovement.RESOLUTION, UpgradeImprovement.SPONSORBLOCK, UpgradeImprovement.SUBTITLES, UpgradeImprovement.CODEC,
        UpgradeImprovement.LENGTH,
    ))
    settings = SiteSettings(
        shows=OtherSites.settings.shows | {SiteSetting.SPONSORBLOCK, SiteSetting.SPONSORBLOCK_SEGMENTS},
        presets=MappingProxyType({
            # Creators keep changing titles and thumbnails for days, and YouTube tests them for up to two weeks.
            SiteSetting.METADATA_REFRESH: "30m,2h,6h,24h,3d,7d,14d",
            SiteSetting.UPGRADE_IMPROVEMENTS: [UpgradeImprovement.RESOLUTION.value, UpgradeImprovement.SPONSORBLOCK.value],
            # A creator trimming a video in YouTube Studio usually cuts a few minutes at most.
            SiteSetting.UPGRADE_LENGTH_MINUTES: 3,
        }),
    )
    accesses = (
        Access(MEMBERS_KEY, "Members only", "Only members of the channel can watch this."),
        Access(PREMIUM_KEY, "YouTube Premium", "Only YouTube Premium subscribers can watch this."),
    )
    # The YouTube Data API key.
    takes_api_key = True
    # A channel's members-only videos sit among its open ones, so its collections start without them.
    shows_locked = False
    creators = True
    creator_presets = CREATOR_PRESETS
    creator_sections = CreatorSectionNames("a playlist", "playlists")
    # A channel's playlists can be the seasons of a collection made from the channel.
    link_seasons = True
