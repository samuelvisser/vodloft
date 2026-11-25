"""How VODLoft searches Odysee: Odysee's own search finds the claims, and the LBRY API Odysee's website uses tells
their titles and pictures."""
from __future__ import annotations

from datetime import datetime, timezone

from ...contract import LinkKind, ResolvedLink, SearchResults
from .. import site_search
from ..search_facts import date, facts, length, plural
from .other_sites import OtherSitesImplementation

_SEARCH = "https://lighthouse.odysee.tv/search"
_CLAIMS = "https://api.na-backend.odysee.com/api/v1/proxy"
_CHANNELS = 5
_VIDEOS = 20


def _page(canonical_url: str) -> str:
    """Odysee's page of a claim: lbry://@channel#f/video#9 is https://odysee.com/@channel:f/video:9."""
    return "https://odysee.com/" + canonical_url.removeprefix("lbry://").replace("#", ":")


def _released(value: dict) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value.get("release_time")), timezone.utc)
    except (TypeError, ValueError):
        return None


class OdyseeImplementation(OtherSitesImplementation):
    key = "lbry"

    def search(self, query: str) -> SearchResults:
        """The best matching channels, then videos, in the order Odysee's search gives them."""
        channels, videos = site_search.at_once(
            lambda: site_search.ask(self.site.name, _SEARCH, params={"s": query, "size": _CHANNELS, "claimType": "channel"}),
            lambda: site_search.ask(self.site.name, _SEARCH, params={
                "s": query, "size": _VIDEOS, "claimType": "file", "mediaType": "video",
            }),
        )
        ids = [hit["claimId"] for hit in [*channels, *videos] if isinstance(hit, dict) and hit.get("claimId")]
        if not ids:
            return SearchResults([])
        answer = site_search.ask(self.site.name, _CLAIMS, params={"m": "claim_search"}, body={
            "jsonrpc": "2.0", "method": "claim_search", "params": {"claim_ids": ids, "page_size": len(ids), "no_totals": True},
        })
        claims = {claim.get("claim_id"): claim for claim in (answer.get("result") or {}).get("items") or []}
        found = []
        for claim_id in ids:
            claim = claims.get(claim_id)
            if not claim or not claim.get("canonical_url"):
                continue
            if claim.get("value_type") == "channel":
                found.append(self._channel(claim))
            elif claim.get("value_type") == "stream" and (claim.get("value") or {}).get("stream_type") == "video":
                found.append(self._video(claim))
        return SearchResults(found)

    def _channel(self, claim: dict) -> ResolvedLink:
        value = claim.get("value") or {}
        return ResolvedLink(
            kind=LinkKind.COLLECTION, slug=claim["claim_id"], url=_page(claim["canonical_url"]),
            title=value.get("title") or claim.get("name") or claim["claim_id"], description=value.get("description") or None,
            image_url=(value.get("thumbnail") or {}).get("url"), site=self.site.name, kind_label="Channel",
            facts=facts(claim.get("name"), plural((claim.get("meta") or {}).get("claims_in_channel"), "upload")),
        )

    def _video(self, claim: dict) -> ResolvedLink:
        value = claim.get("value") or {}
        channel = claim.get("signing_channel") or {}
        return ResolvedLink(
            kind=LinkKind.VIDEO, slug=f"lbry-{claim['claim_id']}", url=_page(claim["canonical_url"]),
            title=value.get("title") or claim.get("name") or claim["claim_id"], description=value.get("description") or None,
            image_url=(value.get("thumbnail") or {}).get("url"),
            author_name=(channel.get("value") or {}).get("title") or channel.get("name"), site=self.site.name,
            kind_label="Video", facts=facts(length((value.get("video") or {}).get("duration")), date(_released(value))),
        )
