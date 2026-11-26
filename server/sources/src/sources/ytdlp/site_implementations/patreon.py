"""How yt-dlp fetches Patreon's posts: only those with a video or sound in them, and their pictures."""
from __future__ import annotations

import logging

from .. import sites
from .other_sites import OtherSitesImplementation

logger = logging.getLogger(__name__)

# Patreon's API gives some posts, such as embedded videos and links, a picture on its own media-u address, which
# answers with an error page instead.
_UNSERVED = "patreon.com/media-u/"
_HOME = "https://www.patreon.com/"
# The kinds of post Patreon has with a video or sound in them, such as video_embed, audio_file, livestream_youtube and
# podcast. Text, images, links and polls are left out.
_MEDIA_KINDS = ("video", "audio", "livestream", "podcast")


def _is_media(post_type: str) -> bool:
    """Whether a post of this kind has a video or sound in it; a post of no known kind might."""
    return not post_type or post_type.startswith(_MEDIA_KINDS)


class PatreonImplementation(OtherSitesImplementation):
    key = "patreon"

    def media_entries(self, listing: dict, entries: list[dict]) -> list[dict]:
        """Only the posts with a video or sound in them. yt-dlp can't look into a post for patrons only, so the kind of
        each post comes from Patreon's API, which tells it for every post. A post the API doesn't tell is kept, for
        yt-dlp's lookup to decide."""
        campaign_id = listing.get("id")
        wanted = {str(entry["id"]) for entry in entries if entry.get("id")}
        if not campaign_id or not wanted or listing.get("extractor_key") != "PatreonCampaign":
            return entries
        try:
            kinds = self._post_kinds(str(campaign_id), wanted)
        except Exception as exc:  # noqa: BLE001 - an undocumented API can fail in any way; yt-dlp's lookups still decide
            logger.info("Keeping every post of Patreon campaign %s, because Patreon did not tell their kinds: %s", campaign_id, exc)
            return entries
        return [entry for entry in entries if _is_media(kinds.get(str(entry.get("id"))) or "")]

    @staticmethod
    def _post_kinds(campaign_id: str, wanted: set[str]) -> dict[str, str]:
        """The kind of each wanted post of the campaign, by its id, asked through yt-dlp's Patreon extractor, which
        gets past Patreon's bot check. Its pages go newest first, so a check of the newest posts reads one page."""
        from yt_dlp import YoutubeDL

        cookies = sites.cookies_for(_HOME)
        options = {"quiet": True, "no_warnings": True, **({"cookiefile": str(cookies)} if cookies else {})}
        kinds: dict[str, str] = {}
        cursor = None
        with YoutubeDL(options) as ydl:
            extractor = ydl.get_info_extractor("PatreonCampaign")
            extractor.initialize()
            while True:
                query = {
                    "fields[post]": "post_type", "filter[campaign_id]": campaign_id, "filter[is_draft]": "false",
                    "sort": "-published_at", "json-api-use-default-includes": "false",
                    **({"page[cursor]": cursor} if cursor else {}),
                }
                answer = extractor._call_api("posts", campaign_id, query=query, note=False)
                for post in answer.get("data") or []:
                    if isinstance(post, dict) and post.get("id"):
                        kinds[str(post["id"])] = str((post.get("attributes") or {}).get("post_type") or "")
                cursor = ((answer.get("meta") or {}).get("pagination") or {}).get("cursors", {}).get("next")
                if cursor is None or wanted <= kinds.keys():
                    return kinds

    def served_picture(self, url: str | None) -> str | None:
        return None if url and _UNSERVED in url else url
