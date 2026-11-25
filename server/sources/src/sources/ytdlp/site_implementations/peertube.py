"""How VODLoft searches PeerTube: through SepiaSearch, the search engine PeerTube's makers run over many PeerTube
servers. Every server has a domain of its own, and yt-dlp only knows the PeerTube servers on its own list, so only the
results on those are shown: VODLoft can add nothing else."""
from __future__ import annotations

from datetime import datetime

from ...contract import LinkKind, ResolvedLink, SearchResults, link_host
from .. import site_search, sites
from ..search_facts import date, facts, length, plural
from .other_sites import OtherSitesImplementation

_API = "https://sepiasearch.org/api/v1/search"
_CHANNELS = 10
_PLAYLISTS = 10
_VIDEOS = 30


def _avatar(item: dict) -> str | None:
    avatars = [avatar for avatar in item.get("avatars") or [] if isinstance(avatar, dict) and avatar.get("url")]
    return max(avatars, key=lambda avatar: avatar.get("width") or 0)["url"] if avatars else None


def _published(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class PeerTubeImplementation(OtherSitesImplementation):
    key = "peertube"

    def search(self, query: str) -> SearchResults:
        """The best matching channels, then playlists, then videos, on the servers VODLoft can add from."""
        def ask(kind: str, count: int) -> list[dict]:
            answer = site_search.ask(self.site.name, f"{_API}/{kind}", params={"search": query, "count": count, "sort": "-match"})
            return [item for item in answer.get("data") or [] if isinstance(item, dict) and item.get("url")]

        channels, playlists, videos = site_search.at_once(
            lambda: ask("video-channels", _CHANNELS), lambda: ask("video-playlists", _PLAYLISTS), lambda: ask("videos", _VIDEOS),
        )
        found = [
            *(self._channel(item) for item in channels if item.get("host") and item.get("name")),
            *(self._playlist(item) for item in playlists if item.get("shortUUID")),
            *(self._video(item) for item in videos),
        ]
        return SearchResults([link for link in found if sites.site_for(link.url).key == self.site.key])

    def _channel(self, item: dict) -> ResolvedLink:
        # SepiaSearch links a channel's page by its older address, which yt-dlp does not read; /c/ is the same page.
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=item["name"], url=f"https://{item['host']}/c/{item['name']}",
            title=item.get("displayName") or item.get("name") or item["url"], description=item.get("description") or None,
            image_url=_avatar(item), site=self.site.name, kind_label="Channel",
            facts=facts(item.get("host"), plural(item.get("followersCount"), "follower"), plural(item.get("videosCount"), "video")),
        )

    def _playlist(self, item: dict) -> ResolvedLink:
        owner = item.get("videoChannel") or item.get("ownerAccount") or {}
        host = item.get("host") or owner.get("host") or link_host(item["url"])
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=item["shortUUID"], url=f"https://{host}/w/p/{item['shortUUID']}",
            title=item.get("displayName") or item["url"], description=item.get("description") or None,
            image_url=item.get("thumbnailUrl"), author_name=owner.get("displayName"), site=self.site.name,
            kind_label="Playlist", facts=facts(host, plural(item.get("videosLength"), "video")),
        )

    def _video(self, item: dict) -> ResolvedLink:
        owner = item.get("channel") or item.get("account") or {}
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"peertube-{item.get('uuid') or item['url']}", url=item["url"],
            title=item.get("name") or item["url"], description=item.get("truncatedDescription") or item.get("description") or None,
            image_url=item.get("thumbnailUrl"), author_name=owner.get("displayName"), site=self.site.name,
            kind_label="Video",
            facts=facts("Live now" if item.get("isLive") else length(item.get("duration")), date(_published(item.get("publishedAt"))),
                        plural(item.get("views"), "view")),
        )
