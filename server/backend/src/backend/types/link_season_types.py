from enum import StrEnum

from sources import ChannelSeason

__all__ = ["ChannelSeason", "CollectionKind", "LinkSeasons", "ListLayout", "ListStatus", "LooseVideos", "NewLinkSeasonAction", "OutsideVideos", "RepeatVideos"]


class LinkSeasons(StrEnum):
    """Whether a channel collection turns the channel's playlists into seasons."""

    OFF = "off"
    ALL = "all"
    """Every playlist is a season, also the ones the channel adds later."""
    SELECTED = "selected"
    """Only the playlists the user keeps on; ``NewLinkSeasonAction`` says what happens with new ones."""


class NewLinkSeasonAction(StrEnum):
    """What happens with a playlist the channel adds later, when only selected playlists are seasons."""

    ASK = "ask"
    """Send a message, and show the playlist in the collection's Seasons dialog to turn on."""
    ADD = "add"
    """Make it a season."""
    IGNORE = "ignore"
    """Leave it off."""


class ListStatus(StrEnum):
    KNOWN = "known"
    NEW = "new"
    """Found after the collection was set up, waiting for the user's choice."""


class OutsideVideos(StrEnum):
    """What a collection does with the videos of its link seasons that its own link does not list, such as another
    channel's video in a playlist."""

    LEAVE_OUT = "leave_out"
    ADD = "add"
    """Add them to the collection, in their link season. They leave again, files and all, once no link season that is
    on lists them."""
    ONLY = "only"
    """Hold nothing but the videos of the link seasons that are on: the link seasons say what the collection holds.
    Its own link, which it may go without, only offers its playlists; a video leaves, files and all, once no link
    season that is on lists it."""


class ListLayout(StrEnum):
    """How a collection whose lists are seasons lays them out."""

    SEASON_EACH = "season_each"
    """Each list is a season, or shares one with the lists the user put together with it."""
    BY_YEAR = "by_year"
    """The lists still decide which videos are in, but the seasons are years, by each video's date. Videos in no
    list join the same year seasons."""


class LooseVideos(StrEnum):
    """Where a collection whose playlists are seasons puts the videos that are in none of them."""

    ONE_SEASON = "one_season"
    """All in one season, named as the Site calls it, such as Videos, shown before the playlists."""
    BY_YEAR = "by_year"
    """A season per upload year, between the playlists by date."""


class RepeatVideos(StrEnum):
    """What a collection does with a video that belongs in several of its seasons, such as a track on several albums."""

    ONE_SEASON = "one_season"
    """One episode, in the season that comes first."""
    EACH_SEASON = "each_season"
    """An episode in each of those seasons, with files of its own, so every season is whole."""


class CollectionKind(StrEnum):
    """What a collection's own link is, set when the collection is added and whenever its link changes."""

    CHANNEL = "channel"
    """A creator's own page of all their uploads, such as a YouTube channel or a Daily Wire show: its feeds are its
    videos, and its lists can be its seasons. Only a channel collection can be in a creator."""
    LIST = "list"
    """One list, such as a playlist or an album."""
    CUSTOM = "custom"
    """No link of its own: a custom collection, which gets all it holds from the lists the user gives it. Given a link
    of its own, it becomes a channel or a list collection, by what the link is."""
