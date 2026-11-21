"""OtherSites: what is yt-dlp's own on every site it downloads from, for every site without a contract of its own.

``OtherSites`` only sets what every yt-dlp site does differently from VODLoft's own defaults in ``Site``; anything
else stays VODLoft's default. A site's own contract subclasses ``OtherSites`` and names only what is different there.
"""
from __future__ import annotations

from dataclasses import fields
from typing import ClassVar

from ...contract import (
    Access,
    CreatorPreset,
    DownloadOptions,
    Site,
    SiteSetting,
    SiteSettings,
    UpgradeChecks,
    UpgradeImprovement,
)

# What yt-dlp says a video needs: ``subscriber_only`` is a membership of the channel and ``premium_only`` the
# site's paid subscription.
MEMBERS_KEY, PREMIUM_KEY = "members", "premium"
# The ways a site with creators offers to keep one, the first the default.
CREATOR_PRESETS = (CreatorPreset.ONE_SHOW, CreatorPreset.PER_LIST, CreatorPreset.PICK)
# Told by the factory: the Site's key and name, and the link's domain.
_FACTORY_FIELDS = frozenset({"key", "name", "domains"})
SITE_FIELDS = frozenset(field.name for field in fields(Site)) - _FACTORY_FIELDS


class OtherSites:
    key: ClassVar[str | None] = None
    """The yt-dlp extractor module the site's contract is for, such as ``youtube``."""
    name: ClassVar[str | None] = None
    """What VODLoft calls the site; None names it after the link's domain."""
    domains: ClassVar[tuple[str, ...]] = ()
    """The site's own domains, such as ``instagram.com``. They tell the site of a link to a page none of its
    extractors handles, such as its home page, which yt-dlp leaves to the generic extractor."""

    # yt-dlp chooses among every version a site has, so each has the quality choices, and it gets the subtitles of
    # any site and writes an info file about each video.
    downloads = DownloadOptions(subtitles=True, quality_choices=True, info_file=True)
    # yt-dlp tells a video's resolutions, codecs, subtitles and length on every site.
    upgrade_checks = UpgradeChecks((
        UpgradeImprovement.RESOLUTION, UpgradeImprovement.SUBTITLES, UpgradeImprovement.CODEC, UpgradeImprovement.LENGTH,
    ))
    # yt-dlp reads the chapters a video comes with on every site that has them.
    settings = SiteSettings(shows=frozenset({SiteSetting.CHAPTERS}))
    # The general names. A site's own contract names only the ones it calls its own way; the factory adds the rest.
    accesses = (
        Access(MEMBERS_KEY, "Subscribers only", "Only subscribers of the channel can watch this."),
        Access(PREMIUM_KEY, "Premium only", "Only the site's paying subscribers can watch this."),
    )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        unknown = {name for name in vars(cls) if not name.startswith("_") and name not in SITE_FIELDS | {"key", "name", "domains"}}
        if unknown:
            raise TypeError(f"{cls.__name__} sets {', '.join(sorted(unknown))}, which a Site does not have")
        if not cls.key:
            raise TypeError(f"{cls.__name__} names no key")
