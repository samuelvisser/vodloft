from enum import StrEnum

from sources import ChannelSeason

__all__ = ["ChannelSeason", "CollectionKind", "LinkSeasons", "ListStatus", "LooseVideos", "NewLinkSeasonAction", "OutsideVideos", "RepeatVideos", "SourceRole"]


class LinkSeasons(StrEnum):
    """Whether a collection takes lists: its channel's playlists and the links the user adds. Each list then says
    what it is: off, a season of its own, or part of the collection (``CollectionList.enabled`` and ``as_season``),
    and ``NewLinkSeasonAction`` says what happens with new ones."""

    OFF = "off"
    ON = "on"


class SourceRole(StrEnum):
    """What one source of a collection is, such as a feed of its channel: a season of its own, part of the
    collection, or off."""

    SEASON = "season"
    PART = "part"
    OFF = "off"


class NewLinkSeasonAction(StrEnum):
    """What happens with a playlist the channel adds later."""

    ASK = "ask"
    """Send a message, and show the playlist in the collection's Seasons dialog to turn on."""
    ADD = "add"
    """Make it a season."""
    CONTENTS = "contents"
    """Include its videos, without a season of its own: contents only."""
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


class LooseVideos(StrEnum):
    """How a collection groups its own videos into seasons: a channel collection the videos of its feeds, beside the
    seasons of its playlists, and a collection made from one list the videos of that list."""

    EVERYTHING = "everything"
    """Only for a channel collection: every video of its feeds in one season, also the ones a playlist that is a season
    has, so the season is the whole channel. It is named after the Site's channel collections, such as Channel."""
    ONE_SEASON = "one_season"
    """All in one season. In a channel collection whose playlists are seasons, only the videos in none of them, named
    as the Site calls them, such as Videos, shown before the playlists; with no playlists as seasons, that season holds
    the whole channel, as with ``EVERYTHING``. In a collection made from one list, the list's own season."""
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
