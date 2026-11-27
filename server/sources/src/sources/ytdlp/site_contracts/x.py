from dataclasses import replace

from ...contract import UpgradeChecks, UpgradeImprovement
from .other_sites import OtherSites


class X(OtherSites):
    key = "twitter"
    name = "X"
    initials = "X"
    domains = ("x.com", "twitter.com")
    icon = "fab:x-twitter"
    # yt-dlp titles a post "<account> - <the start of its text>".
    titles_from_description = True
    # yt-dlp downloads the videos of single posts; it can't list an account's posts, so X has no creators. X has
    # no subtitles, and keeps its videos at 1080p at most.
    downloads = replace(OtherSites.downloads, video_heights=(360, 480, 720, 1080), subtitles=False)
    upgrade_checks = UpgradeChecks((UpgradeImprovement.RESOLUTION, UpgradeImprovement.CODEC, UpgradeImprovement.LENGTH))
    cookies_help = (
        "For posts that are only shown to signed-in viewers, such as sensitive or age-restricted ones. Export a "
        "cookies.txt file from a browser where you are signed in on x.com, and choose it here."
    )
