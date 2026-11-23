from dataclasses import replace

from ...contract import Names
from .feed_section_type import YtdlpFeedSectionType
from .other_sites import OtherSites


class TikTok(OtherSites):
    key = "tiktok"
    name = "TikTok"
    initials = "TT"
    domains = ("tiktok.com",)
    icon = "fab:tiktok"
    # yt-dlp titles a video with the start of its caption, hashtags and all.
    titles_from_description = True
    # Its apps share short links, which redirect to its pages.
    share_hosts = ("vm.tiktok.com", "vt.tiktok.com")
    creators = True
    # An account has one feed of its videos, on its own page.
    section_types = (YtdlpFeedSectionType("videos", Names("video", "videos"), ""),)
    # TikTok has its videos at 1080p at most.
    downloads = replace(OtherSites.downloads, video_heights=(360, 480, 720, 1080))
    cookies_help = (
        "TikTok often refuses to list an account's videos to a server it does not know. Export a cookies.txt file "
        "from a browser where you are signed in on tiktok.com, and choose it here, if adding an account fails or "
        "for videos only signed-in viewers can watch."
    )
