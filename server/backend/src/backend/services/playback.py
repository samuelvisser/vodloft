"""Asking a Source where a video's media is, before VODLoft downloads it."""
from __future__ import annotations

from downloader import EncryptedMediaError, SubscriptionRequiredError
from downloader.lifecycle import DownloadTracker
from sources import Playback, Source


def resolve_playback(
    source: Source, *, slug: str, url: str, title: str, tracker: DownloadTracker, use_cookies: bool | None = None,
) -> Playback:
    """The Source's playback of a video on a page, refusing one it protects with DRM or keeps for subscribers."""
    tracker.preparing("resolve_playback")
    options = {} if use_cookies is None else {"use_cookies": use_cookies}
    playback = source.video_playback(slug=slug, url=url, **options)
    tracker.ensure_active()
    if playback.drm_protected:
        raise EncryptedMediaError(f"{source.name} protects '{title}' with DRM")
    if playback.needs_subscription:
        raise SubscriptionRequiredError(
            f"{source.name} only gives '{title}' to {source.subscription_name or 'paying'} subscribers"
        )
    return playback
