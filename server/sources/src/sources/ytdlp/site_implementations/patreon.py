"""How yt-dlp fetches Patreon's posts."""
from __future__ import annotations

from .other_sites import OtherSitesImplementation

# Patreon's API gives some posts, such as embedded videos and links, a picture on its own media-u address, which
# answers with an error page instead.
_UNSERVED = "patreon.com/media-u/"


class PatreonImplementation(OtherSitesImplementation):
    key = "patreon"

    def served_picture(self, url: str | None) -> str | None:
        return None if url and _UNSERVED in url else url
