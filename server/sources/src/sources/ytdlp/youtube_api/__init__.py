"""The optional YouTube Data API key that speeds up the yt-dlp Source on YouTube.

The key only ever answers catalogue questions: which videos a channel has and
what they are about. yt-dlp still downloads every file, and everything has a
yt-dlp fallback, so a missing, broken or exhausted key only makes VODLoft slower.
"""
from .client import (
    ApiKeyError, ApiNotEnabledError, NotFoundError, QuotaExceededError, TemporaryApiError, YouTubeApiClient,
    YouTubeApiError,
)
from .quota import Share

__all__ = [
    "ApiKeyError",
    "ApiNotEnabledError",
    "NotFoundError",
    "QuotaExceededError",
    "Share",
    "TemporaryApiError",
    "YouTubeApiClient",
    "YouTubeApiError",
]
