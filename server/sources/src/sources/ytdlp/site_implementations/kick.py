"""How VODLoft searches Kick: through the search of Kick's own website, which finds channels."""
from __future__ import annotations

from ...contract import LinkKind, ResolvedLink, SearchResults
from .. import site_search
from ..search_facts import facts, plural
from .other_sites import OtherSitesImplementation

_SEARCH = "https://kick.com/api/search"
_CHANNELS = 20


class KickImplementation(OtherSitesImplementation):
    key = "kick"

    def search(self, query: str) -> SearchResults:
        """The channels whose name matches, as Kick orders them."""
        found = site_search.ask(self.site.name, _SEARCH, params={"searched_word": query})
        channels = [channel for channel in found.get("channels") or [] if channel.get("slug") and not channel.get("is_banned")]
        return SearchResults([self._channel(channel) for channel in channels[:_CHANNELS]])

    def _channel(self, channel: dict) -> ResolvedLink:
        slug, user = channel["slug"], channel.get("user") or {}
        # A channel's own page is its live stream, which yt-dlp only reads while it is live; its videos are a list.
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=slug, url=f"https://kick.com/{slug}/videos", title=user.get("username") or slug,
            description=site_search.text(user.get("bio")), image_url=user.get("profilePic") or None,
            site=self.site.name, kind_label="Channel",
            facts=facts("Live now" if channel.get("isLive") else None, plural(channel.get("followers_count"), "follower")),
        )
