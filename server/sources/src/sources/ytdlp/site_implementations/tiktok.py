"""How yt-dlp does on TikTok what TikTok's contract says it has: an account and its videos."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

from progress_plan import PlanTracker

from ...contract import CreatorDetails
from ... import ytdlp_runner as runner
from .other_sites import OtherSitesImplementation
from sources.ytdlp_options import keep_call_options

logger = logging.getLogger(__name__)

_HOSTS = frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"})
_HANDLE = re.compile(r"^@([\w.-]+)$")


class TikTokImplementation(OtherSitesImplementation):
    key = "tiktok"

    def shared_page(self, url: str) -> str:
        """TikTok's share links lead to the page with tracking parameters only, which are left out."""
        return urlunsplit(urlsplit(url)._replace(query="", fragment=""))

    def creator_root(self, url: str) -> str | None:
        """The account a link of TikTok's is on: its page, or one of its videos."""
        parts = urlsplit(url)
        if (parts.hostname or "").lower() not in _HOSTS:
            return None
        first = next((part for part in parts.path.split("/") if part), "")
        found = _HANDLE.match(first)
        return f"https://www.tiktok.com/@{found.group(1)}" if found else None

    def is_creator_page(self, url: str) -> bool:
        """The account's own page, which lists all its videos."""
        return self.creator_root(url) is not None and len([part for part in urlsplit(url).path.split("/") if part]) == 1

    def creator_details(self, ref: str, plan: PlanTracker) -> CreatorDetails:
        root = self.creator_root(ref)
        if root is None:
            raise runner.YtDlpError("This link is not a TikTok account")
        with ThreadPoolExecutor(max_workers=len(self.feed_types), thread_name_prefix="account-lookup", **keep_call_options()) as pool:
            listings = self.read_feeds(root, pool, plan)
            try:
                info = listings[self.feed_types[0].key].result()
            except runner.YtDlpError as exc:
                logger.info("TikTok did not list %s: %s", root, exc)
                raise runner.YtDlpError(
                    "TikTok did not list this account's videos. Adding a cookies file for TikTok in Settings often helps."
                ) from exc
            sections = self.feed_sections(root, listings)
        handle = root.rsplit("@", 1)[-1]
        first = next((entry for entry in info.get("entries") or [] if isinstance(entry, dict)), {})
        name = info.get("uploader") or info.get("channel") or first.get("uploader") or first.get("channel")
        return CreatorDetails(
            ref=handle, url=root, title=str(name or handle), handle=f"@{handle}", sections=tuple(sections),
        )
