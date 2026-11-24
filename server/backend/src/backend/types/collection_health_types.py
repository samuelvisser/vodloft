from enum import StrEnum


class HealthIssueKind(StrEnum):
    """The checks of the collection health check, each by the kind of issue it finds. A collection stores what the
    checks found of it in its ``health_issues``; the user can turn each check off."""

    MOVES = "moves"
    """Downloads that its season settings put in another season, which wait for its Move action."""
    NEW_LISTS = "new_lists"
    """Lists its channel added later, which wait for the user's choice in its Seasons dialog."""
    CREATORS = "creators"
    """Not a collection's own issue: several collections of one creator that are in no creator yet, which the user
    can group under the creator. VODLoft finds the creator behind each collection for it."""


class HealthLevel(StrEnum):
    """How much a message on Home asks of the user."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


ISSUE_LEVELS: dict[HealthIssueKind, HealthLevel] = {
    HealthIssueKind.MOVES: HealthLevel.WARNING,
    HealthIssueKind.NEW_LISTS: HealthLevel.INFO,
    HealthIssueKind.CREATORS: HealthLevel.INFO,
}
