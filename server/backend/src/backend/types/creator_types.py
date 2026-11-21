from enum import StrEnum


class SectionTarget(StrEnum):
    """Where one section of a creator goes when the creator is added."""

    MAIN = "main"
    """Into the creator's own collection, the show named after the creator: a list as a season of its own."""
    MAIN_LOOSE = "main_loose"
    """A list into the creator's own collection, not as a season: its videos go where the collection's videos in no
    list go. A feed goes into the creator's own collection the same as with ``MAIN``."""
    OWN = "own"
    """Into a collection of its own."""
    EXCLUDE = "exclude"
    """Nowhere, skipped: it is not in the Library, and nothing else changes; its videos stay where the creator's other
    feeds and lists put them. It stays on the creator page, one click from being added."""
    KEEP_OUT = "keep_out"
    """A list nowhere, and its videos out of every collection of the creator too, also of the seasons of its other
    lists, such as a list of reuploads."""


class NewSectionAction(StrEnum):
    """What happens when the daily look finds a section the creator did not have, such as a new playlist."""

    ASK = "ask"
    """Send a message, and show the section on the creator page with the choices."""
    SEASON = "season"
    """Add it to the creator's own collection, as a season of its own. A show still gets a collection of its own."""
    LOOSE = "loose"
    """Add it to the creator's own collection, not as a season: its videos go where the ones in no list go."""
    OWN = "own"
    """Add it as a collection of its own."""
    IGNORE = "ignore"
    """Only list it on the creator page."""


class SectionStatus(StrEnum):
    KNOWN = "known"
    NEW = "new"
    """Found by the daily look, waiting for the user's choice."""
    IGNORED = "ignored"
    """Skipped: not in the Library, and hidden on the creator page."""
    KEPT_OUT = "kept_out"
    """A list that keeps its videos out of every collection of the creator."""
