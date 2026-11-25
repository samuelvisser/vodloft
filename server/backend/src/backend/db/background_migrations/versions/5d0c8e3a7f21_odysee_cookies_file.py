"""Move the cookies file of the odysee Site to the lbry Site.

Odysee's Site key is lbry now, the yt-dlp extractor module its links go to (Alembic revision 4b9e2d7c1a60). A cookies
file kept under the key odysee becomes the lbry Site's, unless that Site has one already.

Revision ID: 5d0c8e3a7f21
Revises: 8f1a7033bae0
"""

from __future__ import annotations

from sources.cookies import site_cookies_path

revision = "5d0c8e3a7f21"
down_revision = "8f1a7033bae0"
title = "Move Odysee's cookies file"


async def migrate(context) -> None:
    old, new = site_cookies_path("odysee"), site_cookies_path("lbry")
    if old.is_file() and not new.exists():
        old.replace(new)
