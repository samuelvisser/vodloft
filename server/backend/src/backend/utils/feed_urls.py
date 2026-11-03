from __future__ import annotations

from fastapi import Request


def request_base_url(request: Request) -> str:
    """The address VODLoft was reached on, without a trailing slash."""
    return str(request.base_url).rstrip("/")


def build_rss_feed_url(
        base_url: str,
        *,
        token: str,
        collection_slug: str,
) -> str:
    """Build the stable feed URL shown for an RSS stream profile, on VODLoft's address ``base_url``."""
    return f"{base_url.rstrip('/')}/feeds/rss/{token}/{collection_slug}.xml"
