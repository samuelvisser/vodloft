"""Your own lines in a Download Profile's Which episodes: Skip, Only download and Keep.

An episode is downloaded when it passes the built-in lines and every Skip and
Only download rule. Keep never stops a download; it protects matching downloads
from retention. Title and description rules match a regular expression anywhere
in the text, using the same safe matching as the regex editor's tester.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, Sequence

from backend.db.models import DownloadProfile, DownloadProfileRule, Episode
from backend.services.regex_check import PatternError, compile_pattern, search
from backend.types.download_profile_types import DurationOperator, EpisodeRuleAction, EpisodeRuleField


class EpisodeRule(Protocol):
    """A rule as stored, or as typed into a form that is not saved yet."""

    action: str
    field: str
    pattern: Optional[str]
    ignore_case: bool
    duration_operator: Optional[str]
    duration_seconds: Optional[int]
    episode_types: Optional[list[str]]
    season_slugs: Optional[list[str]]


def rule_matches(rule: EpisodeRule, episode: Episode) -> Optional[bool]:
    """Whether the episode is what the rule describes; None when the rule cannot tell.

    A duration rule cannot tell for an episode whose length is not known yet. A
    pattern that runs out of time counts as not matching, like in the tester.
    """
    if rule.field == EpisodeRuleField.TYPES:
        return episode.episode_type in (rule.episode_types or ())
    if rule.field == EpisodeRuleField.SEASONS:
        return episode.season is not None and episode.season.slug in (rule.season_slugs or ())
    if rule.field == EpisodeRuleField.DURATION:
        duration = episode.duration or 0
        if duration <= 0 or not rule.duration_seconds:
            return None
        if rule.duration_operator == DurationOperator.SHORTER:
            return duration < rule.duration_seconds
        return duration > rule.duration_seconds

    try:
        compiled = compile_pattern(rule.pattern or "", rule.ignore_case)
    except PatternError:
        return False
    text = episode.title if rule.field == EpisodeRuleField.TITLE else episode.description
    return bool(search(compiled, text))


def rule_leaves_out(rule: EpisodeRule, episode: Episode) -> bool:
    """Whether this rule stops the episode from being downloaded."""
    if rule.action == EpisodeRuleAction.KEEP:
        return False
    matched = rule_matches(rule, episode)
    if matched is None:
        # An episode the rule cannot judge is not left out by it.
        return False
    return matched if rule.action == EpisodeRuleAction.SKIP else not matched


def first_rule_leaving_out(rules: Sequence[EpisodeRule], episode: Episode) -> Optional[int]:
    """The index of the first rule that leaves the episode out, if any."""
    for index, rule in enumerate(rules):
        if rule_leaves_out(rule, episode):
            return index
    return None


def kept_by_rule(rules: Iterable[EpisodeRule], episode: Episode) -> bool:
    """Whether a Keep rule protects the episode's downloads from retention."""
    return any(
        rule.action == EpisodeRuleAction.KEEP and rule_matches(rule, episode) is True
        for rule in rules
    )


def set_profile_rules(profile: DownloadProfile, rules: Sequence[EpisodeRule]) -> None:
    """Replace a profile's own lines with these, in this order."""
    profile.rules = [
        DownloadProfileRule(
            position=position,
            action=str(rule.action),
            field=str(rule.field),
            pattern=rule.pattern if rule.field in (EpisodeRuleField.TITLE, EpisodeRuleField.DESCRIPTION) else None,
            ignore_case=bool(rule.ignore_case) if rule.field in (EpisodeRuleField.TITLE, EpisodeRuleField.DESCRIPTION) else False,
            duration_operator=str(rule.duration_operator) if rule.field == EpisodeRuleField.DURATION else None,
            duration_seconds=rule.duration_seconds if rule.field == EpisodeRuleField.DURATION else None,
            episode_types=list(rule.episode_types or []) if rule.field == EpisodeRuleField.TYPES else None,
            season_slugs=list(rule.season_slugs or []) if rule.field == EpisodeRuleField.SEASONS else None,
        )
        for position, rule in enumerate(rules)
    ]
