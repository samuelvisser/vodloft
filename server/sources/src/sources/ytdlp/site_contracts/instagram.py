from dataclasses import replace

from ...contract import UpgradeChecks, UpgradeImprovement
from .other_sites import OtherSites


class Instagram(OtherSites):
    key = "instagram"
    name = "Instagram"
    domains = ("instagram.com",)
    # yt-dlp downloads single posts and reels; it can't list an account's posts, so Instagram has no creators.
    # Instagram has no subtitles, and keeps its videos at 1080p at most.
    downloads = replace(OtherSites.downloads, video_heights=(360, 480, 720, 1080), subtitles=False)
    upgrade_checks = UpgradeChecks((UpgradeImprovement.RESOLUTION, UpgradeImprovement.CODEC, UpgradeImprovement.LENGTH))
    cookies_help = (
        "Instagram soon stops answering a server that is not signed in, and only shows some posts to signed-in "
        "viewers. Export a cookies.txt file from a browser where you are signed in on instagram.com, preferably "
        "with an account you don't mind losing, and choose it here."
    )
