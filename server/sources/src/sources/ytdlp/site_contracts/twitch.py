from dataclasses import replace
from datetime import timedelta

from ...contract import LIST_TYPE, VIDEO_TAGS, ApiField, EpisodeTag, GuideStep, Names, Retention, SiteApi, RssEpisodeType, SectionKind, SectionRole, SectionType, UpgradeChecks, UpgradeImprovement
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import OtherSites

CLIP_TAG = "clip"


class Twitch(OtherSites):
    key = "twitch"
    name = "Twitch"
    initials = "TW"
    domains = ("twitch.tv",)
    icon = "fab:twitch"
    creators = True
    # A channel's videos are its past broadcasts, highlights and uploads; its clips are short parts of them that
    # anyone may have cut.
    episode_tags = (
        *VIDEO_TAGS,
        EpisodeTag(
            CLIP_TAG, "Clip", "A short part of a broadcast that a viewer or the streamer cut", Names("clip", "clips"),
            selected_by_default=False, rss_episode_type=RssEpisodeType.BONUS,
        ),
    )
    # A channel's Videos and Clips, and its collections. Twitch calls its playlists collections, which is VODLoft's
    # word for something else, so VODLoft calls them playlists.
    section_types = (
        YtdlpFeedSectionType("videos", Names("video", "videos"), "videos?filter=all"),
        YtdlpFeedSectionType("clips", Names("clip", "clips"), "clips?filter=clips&range=all", role=SectionRole.SHORT, episode_tag=CLIP_TAG),
        SectionType(LIST_TYPE, SectionKind.LIST, Names("playlist", "playlists")),
    )
    link_seasons = True
    # Twitch keeps highlights, uploads and clips, but deletes past broadcasts after a while.
    retention = Retention(
        # Twitch keeps them 7 days for most streamers and 60 days for Partners, Affiliates and Turbo users.
        timedelta(days=7),
        "Twitch deletes past broadcasts after 7 to 60 days, depending on the streamer's account. Highlights, "
        "uploads and clips stay until the streamer deletes them.",
    )
    # Twitch's own API finds channels by name. It is free, with an application the user registers at dev.twitch.tv.
    searchable = True
    site_api = SiteApi(
        "Twitch API",
        (ApiField("client_id", "Client ID"), ApiField("client_secret", "Client secret", secret=True)),
        "Optional. With a free Twitch application, you can search Twitch's channels by name on Add Media. "
        "VODLoft only reads public data with it, and works on Twitch without it.",
        (
            GuideStep(
                "Sign in at the Twitch Developer Console. Twitch asks you to turn on two-factor authentication first.",
                "Open the console", "https://dev.twitch.tv/console/apps",
            ),
            GuideStep(
                'Register an application. Any name works, such as "VODLoft". Use http://localhost as its OAuth '
                'redirect URL, choose any category, and choose Confidential as the client type.',
                "Register an application", "https://dev.twitch.tv/console/apps/create",
            ),
            GuideStep("Open the application under Manage, copy its Client ID, and choose New Secret to get its client secret."),
        ),
        searches=True,
    )
    # Twitch streams and keeps its videos at 1080p at most, and has no subtitles.
    downloads = replace(OtherSites.downloads, video_heights=(360, 480, 720, 1080), subtitles=False)
    upgrade_checks = UpgradeChecks((UpgradeImprovement.RESOLUTION, UpgradeImprovement.CODEC, UpgradeImprovement.LENGTH))
