"""How VODLoft searches Niconico: through its official search API, which finds videos."""
from __future__ import annotations

from datetime import datetime

from ...contract import LinkKind, ResolvedLink, SearchResults
from .. import site_search
from ..search_facts import date, facts, length, plural
from .other_sites import OtherSitesImplementation

_SEARCH = "https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
_VIDEOS = 20
# Niconico asks every caller of its search API to name itself.
_CONTEXT = "VODLoft"


def _started(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class NiconicoImplementation(OtherSitesImplementation):
    key = "niconico"

    def search(self, query: str) -> SearchResults:
        """The videos whose title or tags match, the most watched first: the API has no order by how well they
        match."""
        found = site_search.ask(self.site.name, _SEARCH, params={
            "q": query, "targets": "title,tags", "_sort": "-viewCounter", "_limit": _VIDEOS, "_context": _CONTEXT,
            "fields": "contentId,title,description,viewCounter,lengthSeconds,startTime,thumbnailUrl",
        })
        return SearchResults([self._video(item) for item in found.get("data") or [] if item.get("contentId")])

    def _video(self, item: dict) -> ResolvedLink:
        content_id = item["contentId"]
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"niconico-{content_id}", url=f"https://www.nicovideo.jp/watch/{content_id}",
            title=item.get("title") or content_id, description=site_search.text(item.get("description")),
            image_url=item.get("thumbnailUrl"), site=self.site.name, kind_label="Video",
            facts=facts(length(item.get("lengthSeconds")), date(_started(item.get("startTime"))),
                        plural(item.get("viewCounter"), "view")),
        )
