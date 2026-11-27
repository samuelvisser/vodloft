"""Every kind of thing VODLoft tells you about, in one registry.

VODLoft tells you things in two ways. A **state** is true until someone fixes or answers it, such as a destination
that keeps failing: Home shows it under Needs attention while it is open. An **event** happened once, such as a
finished download: rules send it as a message. Both are kinds in this registry, and each kind's severity sets where
it goes by default. A state that opens also sends an event of the same kind, so every rule can hear about it.

Messages and Home both read their kinds from here, and so can workers and endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from backend.security.access import Area, Level


class Severity(StrEnum):
    PROBLEM = "problem"
    """Something is broken and stays broken until someone acts."""
    NEEDS_YOU = "needs_you"
    """Nothing is broken, but VODLoft waits for a choice."""
    TIP = "tip"
    """Advice VODLoft has, such as collections to group under a creator. Nothing waits for it."""
    NEWS = "news"
    """Something went as it should. Never a Home alert."""


class Shape(StrEnum):
    STATE = "state"
    """Stored while it is true: Home shows it until it resolves or is put off."""
    EVENT = "event"
    """Happened once: rules send it, and nothing resolves it."""


class Tone(StrEnum):
    """How a message looks where it arrives, such as Apprise's success or failure styling."""

    SUCCESS = "success"
    FAILURE = "failure"
    INFO = "info"


class Happening(StrEnum):
    EPISODE_DOWNLOADED = "episode_downloaded"
    EPISODE_REPLACED = "episode_replaced"
    EPISODE_DELETED = "episode_deleted"
    DOWNLOAD_FAILED = "download_failed"
    NEW_EPISODES = "new_episodes"
    SIGN_IN_NEEDED = "sign_in_needed"
    TASK_FAILING = "task_failing"
    DESTINATION_FAILING = "destination_failing"
    DISK_ALMOST_FULL = "disk_almost_full"
    UPDATE_AVAILABLE = "update_available"
    QUICK_DOWNLOAD_FINISHED = "quick_download_finished"
    NEW_LISTS_FOUND = "new_lists_found"
    EVERYTHING = "everything"
    """Only for a daily summary: everything that happened that day."""


@dataclass(frozen=True)
class HappeningDefinition:
    happening: Happening
    when: str
    """How a rule's sentence starts: "When <when> …"."""
    severity: Severity
    tone: Tone
    shape: Shape = Shape.EVENT
    collections: bool = False
    """Whether it belongs to a Collection, so a rule can choose which Collections."""
    actions: bool = False
    """Whether actions (media server refresh, webhook, script) can run on it."""
    personal: bool = False
    """Whether a person can choose it on their own page."""
    audience: tuple[Area, Level] = (Area.SETTINGS, Level.MANAGE)
    """Who may see an open state of it on Home: everyone with at least this level in this area."""

    @property
    def problem(self) -> bool:
        return self.severity == Severity.PROBLEM


HAPPENINGS: tuple[HappeningDefinition, ...] = (
    HappeningDefinition(
        Happening.EPISODE_DOWNLOADED, "an episode is downloaded", Severity.NEWS, Tone.SUCCESS,
        collections=True, actions=True, personal=True,
    ),
    HappeningDefinition(
        Happening.EPISODE_REPLACED, "a download is replaced by a better version", Severity.NEWS, Tone.SUCCESS,
        collections=True, actions=True, personal=True,
    ),
    HappeningDefinition(
        Happening.EPISODE_DELETED, "a download is deleted", Severity.NEWS, Tone.INFO, collections=True, actions=True,
    ),
    HappeningDefinition(
        Happening.DOWNLOAD_FAILED, "a download fails after its retries", Severity.PROBLEM, Tone.FAILURE,
        collections=True,
    ),
    HappeningDefinition(
        Happening.NEW_EPISODES, "new episodes are found but not downloaded", Severity.NEWS, Tone.INFO,
        collections=True, personal=True,
    ),
    HappeningDefinition(
        Happening.SIGN_IN_NEEDED, "a sign-in expires or a site wants cookies", Severity.PROBLEM, Tone.FAILURE,
    ),
    HappeningDefinition(
        Happening.TASK_FAILING, "a task keeps failing", Severity.PROBLEM, Tone.FAILURE, Shape.STATE,
        audience=(Area.TASKS, Level.VIEW),
    ),
    HappeningDefinition(
        Happening.DESTINATION_FAILING, "a destination keeps failing", Severity.PROBLEM, Tone.FAILURE, Shape.STATE,
    ),
    HappeningDefinition(
        Happening.DISK_ALMOST_FULL, "the disk is almost full", Severity.PROBLEM, Tone.FAILURE, Shape.STATE,
    ),
    HappeningDefinition(Happening.UPDATE_AVAILABLE, "a VODLoft update is out", Severity.NEWS, Tone.INFO),
    HappeningDefinition(
        Happening.QUICK_DOWNLOAD_FINISHED, "my Quick download finishes", Severity.NEWS, Tone.SUCCESS, personal=True,
    ),
    HappeningDefinition(
        Happening.NEW_LISTS_FOUND, "a collection finds a new playlist", Severity.NEEDS_YOU, Tone.INFO,
        collections=True, personal=True,
    ),
    HappeningDefinition(
        Happening.EVERYTHING, "anything happens", Severity.NEWS, Tone.INFO, collections=True, personal=True,
    ),
)
DEFINITIONS: Mapping[Happening, HappeningDefinition] = MappingProxyType(
    {definition.happening: definition for definition in HAPPENINGS}
)
