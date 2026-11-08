"""Give each Site its own cookies file, in place of one file per Source.

yt-dlp kept one cookies file for every site it fetches, and NPO Start one of its own. Each
Site now has a cookies file in ``cookies/`` in the config directory, which every Source uses on
that Site. yt-dlp's file is sorted into the Sites its cookies are for, adding the Sites a domain
alone tells, such as YouTube. Cookies of a domain no Site is known for yet, such as twitch.tv
before a Twitch collection is added, are kept in ``yt-dlp/cookies-not-sorted.txt``, to choose
again under Settings › Sources › Sign-ins once the Site is there. NPO Start's file becomes the
NPO Start Site's file.

Revision ID: 305a9510537f
Revises: b41e6d2a9c75
"""

from __future__ import annotations

import asyncio
import logging
import os

from config.settings.base import get_config_path


revision = "305a9510537f"
down_revision = "b41e6d2a9c75"
title = "Give each Site its own cookies file"

logger = logging.getLogger(__name__)

_NPO_SITE = "npo"


def _sort_ytdlp_cookies() -> None:
    from backend.services.site_cookies import add_cookies_file
    from sources import cookies as cookie_files

    path = get_config_path().parent / "yt-dlp" / "cookies.txt"
    if not path.is_file():
        return
    content = path.read_bytes()
    try:
        result = add_cookies_file(content)
    except ValueError:
        logger.warning("Left %s as it is, because it is not a cookies file", path)
        return
    for site in result.sites:
        logger.info("Moved %s cookies of yt-dlp's cookies file to %s", site.cookie_count, site.name)
    if result.other_domains:
        other = set(result.other_domains)
        lines = cookie_files.cookie_lines(content.decode("utf-8", errors="replace"))
        kept = path.with_name("cookies-not-sorted.txt")
        cookie_files.store(kept, cookie_files.cookies_file(
            [line for line in lines if cookie_files.cookie_domain(line) in other]
        ))
        logger.warning(
            "No Site is known for the cookies of %s yet; they are kept in %s",
            ", ".join(result.other_domains), kept,
        )
    path.unlink()


def _move_npo_cookies() -> None:
    from sources import cookies as cookie_files

    path = get_config_path().parent / "npo" / "cookies.txt"
    if not path.is_file():
        return
    target = cookie_files.site_cookies_path(_NPO_SITE)
    target.parent.mkdir(parents=True, exist_ok=True)
    # NPO Start's own file wins over npo.nl cookies yt-dlp's file had.
    os.replace(path, target)
    os.chmod(target, 0o600)
    logger.info("Moved NPO Start's cookies file to %s", target)


async def migrate(context) -> None:
    context.update_progress(0, 2, "Sorting yt-dlp's cookies file into Sites")
    await asyncio.to_thread(_sort_ytdlp_cookies)
    context.raise_if_canceled()
    context.update_progress(1, 2, "Moving NPO Start's cookies file")
    await asyncio.to_thread(_move_npo_cookies)
    context.update_progress(2, 2, "Gave each Site its own cookies file")
