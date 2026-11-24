from enum import StrEnum


class HealthIssueKind(StrEnum):
    """What the collection health check can find a collection needing the user for, as stored in a collection's
    ``health_issues``."""

    MOVES = "moves"
    """Downloads that its season settings put in another season, which wait for its Move action."""
