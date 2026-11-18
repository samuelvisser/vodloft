from enum import StrEnum


class SectionTarget(StrEnum):
    """Where one section of a channel goes when the channel is added."""

    MAIN = "main"
    """Into the channel's own collection, the show named after the channel."""
    OWN = "own"
    """Into a collection of its own."""
    SKIP = "skip"
    """Nowhere: it stays on the channel page, one click from being added."""


class NewSectionAction(StrEnum):
    """What happens when the daily look finds a section the channel did not have, such as a new playlist."""

    ASK = "ask"
    """Send a message, and show the section on the channel page with the choices."""
    SEASON = "season"
    """Add it to the channel's own collection, as a season of its own. A show still gets a collection of its own."""
    OWN = "own"
    """Add it as a collection of its own."""
    IGNORE = "ignore"
    """Only list it on the channel page."""


class SectionStatus(StrEnum):
    KNOWN = "known"
    NEW = "new"
    """Found by the daily look, waiting for the user's choice."""
    IGNORED = "ignored"
