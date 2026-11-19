from enum import StrEnum


class LinkPlacement(StrEnum):
    """Where the videos of one of a collection's links go."""

    SITE_SEASONS = "site_seasons"
    """The Site's own seasons, or a season per upload year when it has none."""
    ONE_SEASON = "one_season"
    """One season named after the link, such as a playlist."""
    SPECIALS = "specials"
    """Specials, season 0."""
