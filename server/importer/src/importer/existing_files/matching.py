"""Matching files to episodes, strongest evidence first.

Each file gets the strongest evidence that names exactly one episode:

1. Recorded path: another program recorded this exact file for the episode.
2. Expected path: the profile's template, rendered for the episode, names this file.
3. Id in the name: ``[dQw4w9WgXcQ]`` or ``.dQw4w9WgXcQ.`` in the file name.
4. Sidecar: an ``.info.json`` or ``.nfo`` next to the file names the episode.
5. Template pattern: a template reads values out of the path that fit one episode.
6. Title and date: the name holds the episode's title, and its date if any.

The first four are certain, a template pattern is likely, and a title match
needs a person to check it. Two files for one episode, or one file that fits
several episodes, are never taken for certain.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

from .normal import normalise, normalise_path
from .patterns import PathPattern
from .scanning import FoundFile

Evidence = Literal["recorded", "expected_path", "id_in_name", "sidecar", "template", "title_date"]
Confidence = Literal["certain", "likely", "review"]
_CONFIDENCE: dict[Evidence, Confidence] = {
    "recorded": "certain", "expected_path": "certain", "id_in_name": "certain", "sidecar": "certain",
    "template": "likely", "title_date": "review",
}
_STRENGTH: dict[Evidence, int] = {evidence: index for index, evidence in enumerate(_CONFIDENCE)}
_DATE = re.compile(r"(?<!\d)(\d{4})[-_. ]?(\d{2})[-_. ]?(\d{2})(?!\d)")
_SIDECAR_LIMIT = 4 * 1024 * 1024


@dataclass(frozen=True)
class EpisodeFacts:
    id: int
    title: str
    site_id: str | None = None
    date: date | None = None
    urls: tuple[str, ...] = ()
    expected_path: str | None = None
    """The profile's template rendered for the episode, without extension, as a ``/downloads/…`` path."""
    values: Mapping[str, str] = field(default_factory=dict)
    """The episode's template variables, for template patterns."""


@dataclass(frozen=True)
class FileMatch:
    path: str
    """As a ``/downloads/…`` path."""
    size: int
    episode_id: int | None
    evidence: Evidence | None
    confidence: Confidence | None
    candidates: tuple[int, ...] = ()
    """For a match to check: the episodes it could be, best first."""
    note: str | None = None


@dataclass(frozen=True)
class MatchResult:
    files: tuple[FileMatch, ...]

    def count(self, confidence: Confidence | None) -> int:
        return sum(1 for item in self.files if item.confidence == confidence)


def _id_in_name(name: str, site_id: str) -> bool:
    return f"[{site_id}]" in name or f".{site_id}." in name or f" {site_id}." in name


def _sidecar_ids(read: Callable[[str], bytes | None], file: FoundFile, folder: str) -> set[str]:
    """Ids and URLs an .info.json or .nfo next to the file names."""
    found: set[str] = set()
    for sidecar in file.sidecars:
        lowered = sidecar.lower()
        if not (lowered.endswith(".info.json") or lowered.endswith(".nfo")):
            continue
        data = read(f"{folder}{sidecar}")
        if not data:
            continue
        text = data[:_SIDECAR_LIMIT].decode("utf-8", "replace")
        if lowered.endswith(".info.json"):
            try:
                info = json.loads(text)
            except ValueError:
                continue
            if isinstance(info, dict):
                for key in ("id", "display_id", "webpage_url", "original_url"):
                    value = info.get(key)
                    if isinstance(value, str) and value:
                        found.add(value)
        else:
            found.update(re.findall(r"[A-Za-z0-9_\-:/.?=&%]{6,}", text))
    return found


def _dates(text: str) -> set[date]:
    out: set[date] = set()
    for year, month, day in _DATE.findall(text):
        try:
            out.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return out


def match_files(
    files: Sequence[FoundFile],
    episodes: Sequence[EpisodeFacts],
    *,
    folder: str,
    patterns: Iterable[PathPattern] = (),
    recorded: Mapping[str, int] | None = None,
    read: Callable[[str], bytes | None] = lambda _path: None,
) -> MatchResult:
    """Match the files found under ``folder`` (a ``/downloads/…`` path) to episodes.

    ``recorded`` maps ``/downloads/…`` paths another program recorded to episode ids.
    ``read`` returns the contents of a sidecar, by ``/downloads/…`` path.
    """
    folder = folder.rstrip("/") + "/"
    recorded = recorded or {}
    by_id = {episode.id: episode for episode in episodes}
    by_site_id: dict[str, list[int]] = defaultdict(list)
    by_url: dict[str, list[int]] = defaultdict(list)
    by_expected: dict[str, list[int]] = defaultdict(list)
    for episode in episodes:
        if episode.site_id:
            by_site_id[episode.site_id].append(episode.id)
        for url in episode.urls:
            by_url[url].append(episode.id)
        if episode.expected_path:
            by_expected[episode.expected_path].append(episode.id)
    pattern_indexes = []
    for pattern in patterns:
        index: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for episode in episodes:
            if all(variable in episode.values for variable in pattern.variables):
                index[tuple(normalise(str(episode.values[variable])) for variable in pattern.variables)].append(episode.id)
        pattern_indexes.append((pattern, index))
    titles = [(episode.id, normalise(episode.title)) for episode in episodes if normalise(episode.title)]

    def certain(file: FoundFile, path: str) -> tuple[Evidence, list[int]] | None:
        if path in recorded and recorded[path] in by_id:
            return "recorded", [recorded[path]]
        stem_path = path.rsplit(".", 1)[0]
        if stem_path in by_expected:
            return "expected_path", by_expected[stem_path]
        name = path.rsplit("/", 1)[-1]
        named = sorted({episode_id for site_id, ids in by_site_id.items() if _id_in_name(name, site_id) for episode_id in ids})
        if named:
            return "id_in_name", named
        if file.sidecars:
            ids = _sidecar_ids(read, file, path.rsplit("/", 1)[0] + "/")
            matched = sorted({episode_id for value in ids for episode_id in (*by_site_id.get(value, ()), *by_url.get(value, ()))})
            if matched:
                return "sidecar", matched
        return None

    def from_template(path: str) -> list[int]:
        normalised = normalise_path(path.rsplit(".", 1)[0])
        found: set[int] = set()
        for pattern, index in pattern_indexes:
            for values in pattern.read(normalised):
                if all(variable in values for variable in pattern.variables):
                    found.update(index.get(tuple(values[variable] for variable in pattern.variables), ()))
        return sorted(found)

    def from_title(path: str) -> list[int]:
        name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        normalised = normalise(name)
        if not normalised:
            return []
        dates = _dates(name)
        scored: list[tuple[float, int]] = []
        for episode_id, title in titles:
            if title in normalised:
                score = 1.0
            else:
                ratio = difflib.SequenceMatcher(None, title, normalised).quick_ratio()
                if ratio < 0.8:
                    continue
                score = difflib.SequenceMatcher(None, title, normalised).ratio()
                if score < 0.8:
                    continue
            episode_date = by_id[episode_id].date
            if dates and episode_date is not None:
                if any(abs((found - episode_date).days) <= 1 for found in dates):
                    score += 0.5
                else:
                    score -= 0.5
            scored.append((score, episode_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [episode_id for score, episode_id in scored[:3] if score >= 0.8]

    matches: list[FileMatch] = []
    for file in files:
        path = folder + file.path
        found = certain(file, path)
        if found is None:
            ids = from_template(path)
            found = ("template", ids) if ids else None
        if found is None:
            ids = from_title(path)
            found = ("title_date", ids) if ids else None
        if found is None:
            matches.append(FileMatch(path, file.size, None, None, None))
            continue
        evidence, ids = found
        if len(ids) == 1:
            matches.append(FileMatch(path, file.size, ids[0], evidence, _CONFIDENCE[evidence]))
        else:
            matches.append(FileMatch(
                path, file.size, ids[0] if evidence == "title_date" else None, evidence, "review", tuple(ids),
                None if evidence == "title_date" else "This file fits more than one episode",
            ))
    return MatchResult(tuple(_settle_conflicts(matches)))


def _settle_conflicts(matches: list[FileMatch]) -> list[FileMatch]:
    """Two files for one episode: the stronger evidence keeps it; equal evidence goes to review."""
    by_episode: dict[int, list[int]] = defaultdict(list)
    for index, item in enumerate(matches):
        if item.episode_id is not None:
            by_episode[item.episode_id].append(index)
    for episode_id, indexes in by_episode.items():
        if len(indexes) < 2:
            continue
        strongest = min(_STRENGTH[matches[index].evidence] for index in indexes)  # type: ignore[index]
        winners = [index for index in indexes if _STRENGTH[matches[index].evidence] == strongest]  # type: ignore[index]
        for index in indexes:
            item = matches[index]
            if index in winners and len(winners) == 1:
                continue
            matches[index] = replace(
                item, confidence="review", candidates=item.candidates or (episode_id,),
                note="Another file matches this episode too",
            )
    return matches
