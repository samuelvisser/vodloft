from enum import StrEnum


class SectionTarget(StrEnum):
    """Where one section of a channel goes when the channel is added."""

    MAIN = "main"
    """Into the channel's own collection, the show named after the channel."""
    OWN = "own"
    """Into a collection of its own."""
    SKIP = "skip"
    """Nowhere: it stays on the channel page, one click from being added."""
