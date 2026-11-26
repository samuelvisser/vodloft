"""How VODLoft searches Dailymotion: through its public API, which needs no key."""
from __future__ import annotations

from datetime import datetime, timezone

from ...contract import LinkKind, ResolvedLink, SearchResults
from .. import site_search
from ..search_facts import date, facts, length, plural
from .other_sites import OtherSitesImplementation

_API = "https://api.dailymotion.com"
_CHANNELS = 5
_VIDEOS = 20
_CHANNEL_FIELDS = "id,screenname,username,url,description,avatar_360_url,videos_total,followers_total"
_VIDEO_FIELDS = "id,title,url,description,thumbnail_360_url,duration,created_time,views_total,owner.screenname"


class DailymotionImplementation(OtherSitesImplementation):
    key = "dailymotion"

    def search(self, query: str) -> SearchResults:
        """The best matching channels, then videos. Dailymotion only searches playlists for a signed-in user."""
        channels, videos = site_search.at_once(
            lambda: site_search.ask(self.site.name, f"{_API}/users", params={
                "search": query, "sort": "relevance", "limit": _CHANNELS, "fields": _CHANNEL_FIELDS,
            }),
            lambda: site_search.ask(self.site.name, f"{_API}/videos", params={
                "search": query, "sort": "relevance", "limit": _VIDEOS, "fields": _VIDEO_FIELDS,
            }),
        )
        found = [self._channel(item) for item in channels.get("list") or [] if item.get("username") and item.get("videos_total")]
        found += [self._video(item) for item in videos.get("list") or [] if item.get("id")]
        return SearchResults(found)

    def _channel(self, item: dict) -> ResolvedLink:
        username = item["username"]
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=username, url=item.get("url") or f"https://www.dailymotion.com/{username}",
            title=item.get("screenname") or username, description=site_search.text(item.get("description")),
            image_url=item.get("avatar_360_url"), site=self.site.name, kind_label="Channel",
            facts=facts(plural(item.get("followers_total"), "follower"), plural(item.get("videos_total"), "video")),
        )

    def _video(self, item: dict) -> ResolvedLink:
        created = item.get("created_time")
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"dailymotion-{item['id']}",
            url=item.get("url") or f"https://www.dailymotion.com/video/{item['id']}", title=item.get("title") or item["id"],
            description=site_search.text(item.get("description")), image_url=item.get("thumbnail_360_url"),
            author_name=item.get("owner.screenname"), site=self.site.name, kind_label="Video",
            facts=facts(
                length(item.get("duration")),
                date(datetime.fromtimestamp(created, timezone.utc) if isinstance(created, (int, float)) else None),
                plural(item.get("views_total"), "view"),
            ),
        )
