"""Who a SoundCloud sign-in token signs in as, asked through yt-dlp's SoundCloud extractor, which keeps the key
SoundCloud's web API takes up to date."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def account_of(token: str) -> str | None:
    """The name of the account the token signs in as, or None when SoundCloud does not accept it."""
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        extractor = ydl.get_info_extractor("Soundcloud")
        try:
            extractor.initialize()
            me = extractor._call_api(
                extractor._API_V2_BASE + "me", None, headers={"Authorization": f"OAuth {token}"}, note=False, fatal=False,
            )
        except Exception as exc:
            logger.info("Could not ask SoundCloud who a token signs in as: %s", type(exc).__name__)
            raise
    if not isinstance(me, dict):
        return None
    return str(me.get("username") or me.get("permalink") or "") or None
