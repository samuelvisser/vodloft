from enum import StrEnum


class SeasonType(StrEnum):
    NORMAL = "normal"
    EXTRA = "extra"


class SeasonOrigin(StrEnum):
    """Where a season came from."""

    SITE = "site"
    """The Site has it itself, such as a Daily Wire show's seasons or an NPO Start series' seasons."""
    LIST = "list"
    """One of the Site's lists, such as a YouTube playlist or a SoundCloud album, that VODLoft made a season."""
    VODLOFT = "vodloft"
    """VODLoft made it itself, such as a season per year, the season of what is in no list, or the season of a video
    split by chapter."""
