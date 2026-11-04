"""Which episodes filters for tests, in the order a Download Profile applies them."""
from __future__ import annotations

from types import SimpleNamespace


def line(action, field, *, pattern=None, duration_operator=None, duration_seconds=None, episode_types=None,
         season_slugs=None, include_upcoming=False, days=None, count=None, starting_from=None):
    return SimpleNamespace(
        action=action, field=field, pattern=pattern, duration_operator=duration_operator,
        duration_seconds=duration_seconds, episode_types=episode_types, season_slugs=season_slugs,
        include_upcoming=include_upcoming, days=days, count=count, starting_from=starting_from,
    )


def only_types(*keys):
    return line("only", "types", episode_types=list(keys))


def only_seasons(*slugs, upcoming=False):
    return line("only", "seasons", season_slugs=list(slugs), include_upcoming=upcoming)


def latest(count, action="only"):
    return line(action, "published", count=count)


def published_days(days, action="only"):
    return line(action, "published", days=days)


def published_since(day):
    return line("only", "published", starting_from=day)


def downloaded_days(days, action="only"):
    return line(action, "downloaded", days=days)


def with_filters(profile, *filters):
    """Give the profile these filters, in this order, and return it."""
    from backend.services.episode_filters import set_profile_filters

    set_profile_filters(profile, list(filters))
    return profile


def filter_rows(*filters):
    """These filters as a profile's rows, to pass as DownloadProfile(filters=...)."""
    from backend.db.models import DownloadProfile

    return with_filters(DownloadProfile(), *filters).filters
