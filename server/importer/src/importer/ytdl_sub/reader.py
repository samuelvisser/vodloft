"""ytdl-sub's configuration: each subscription with the presets and values it resolves to.

ytdl-sub keeps no database. ``subscriptions.yaml`` lists the subscriptions, grouped under keys that
name presets (``Jellyfin TV Show by Date | Max 1080p``) and indent values (``= Documentaries``),
and ``config.yaml`` adds custom presets on top of ytdl-sub's own. A subscription is all of its
presets merged in ytdl-sub's order, then the file preset ``__preset__``, then its own values.

ytdl-sub's own presets are known by name (see :mod:`.presets`), so reading a configuration never
needs ytdl-sub itself.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from .presets import BUILTINS, Builtin

FILE_PRESET = "__preset__"


class YtdlSubReadError(ValueError):
    """The files are not a ytdl-sub configuration VODLoft can read."""


@dataclass(frozen=True)
class Subscription:
    name: str
    presets: tuple[str, ...]
    """The presets the subscription names, as written, without the file preset."""
    applied: tuple[str, ...]
    """Every preset it uses, its parents included, in the order ytdl-sub merges them."""
    config: dict
    """Everything the presets and the subscription set, merged, in ytdl-sub's keys."""
    urls: tuple[str, ...] = ()
    """The links it downloads, in order."""
    unknown: tuple[str, ...] = ()
    """Presets it names that are neither ytdl-sub's nor in config.yaml."""
    map: bool = False
    """Written as a ``+`` map, which only ytdl-sub's music video presets read."""
    categories: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """A ``+`` map's categories, such as Concerts, each with its links in order."""

    @property
    def overrides(self) -> dict[str, object]:
        return self.config.get("overrides") or {}

    def builtins(self) -> list[tuple[str, Builtin]]:
        return [(name, BUILTINS[name]) for name in self.applied if name in BUILTINS]


@dataclass(frozen=True)
class YtdlSubData:
    subscriptions: tuple[Subscription, ...]
    custom_presets: tuple[str, ...] = ()


def _load(path: Path) -> dict:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise YtdlSubReadError(f"{path.name} is not a YAML file VODLoft can read ({exc})") from exc
    if not isinstance(loaded, dict):
        raise YtdlSubReadError(f"{path.name} does not hold ytdl-sub's settings")
    return loaded


def merge(*configs: Mapping) -> dict:
    """``configs`` merged as ytdl-sub merges presets: later values win, lists add up."""
    merged: dict = {}
    for config in configs:
        for key, value in config.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
                merged[key] = merge(merged[key], value)
            elif isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = [*merged[key], *value]
            elif isinstance(value, Mapping):
                merged[key] = merge(value)
            else:
                merged[key] = list(value) if isinstance(value, list) else value
    return merged


class _Presets:
    def __init__(self, custom: Mapping[str, Mapping]) -> None:
        self.custom = custom

    def known(self, name: str) -> bool:
        return name in self.custom or name in BUILTINS

    def sequence(self, names: Sequence[str], seen: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
        """Every preset of ``names`` and their parents, in merge order, and the names it can't find."""
        order: list[str] = []
        unknown: list[str] = []
        for name in names:
            if name in seen:
                raise YtdlSubReadError(f"The preset {name} uses itself")
            if name in self.custom:
                parents = self.custom[name].get("preset") or []
            elif name in BUILTINS:
                parents = BUILTINS[name].parents
            else:
                unknown.append(name)
                continue
            parents = [parents] if isinstance(parents, str) else list(parents)
            inner, missing = self.sequence(parents, (*seen, name))
            order += [*inner, name]
            unknown += missing
        return order, unknown

    def config(self, name: str) -> Mapping:
        if name in self.custom:
            return {key: value for key, value in self.custom[name].items() if key != "preset"}
        return BUILTINS[name].config


def _script_list(text: str) -> list[object] | None:
    """A ytdl-sub array written as a script, such as ``{ ['a', "b"] }``; None when it is any other script."""
    match = re.fullmatch(r"\s*\{\s*(\[.*\])\s*\}\s*", text, re.DOTALL)
    if not match:
        return None
    try:
        value = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, list) else None


def override_list(value: object) -> list[str] | None:
    """An override that holds a list, written in YAML or as a script array; None when it is no list."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        found = _script_list(value)
        return [str(item) for item in found] if found is not None else None
    return None


def _indent_overrides(indents: Sequence[str]) -> dict[str, str]:
    return {f"subscription_indent_{index + 1}": value for index, value in enumerate(indents)}


Categories = tuple[tuple[str, tuple[str, ...]], ...]


def _categories(value: Mapping) -> Categories:
    """A ``+`` map's categories and their links: each category holds one link or a list of them. A link can also be
    a map with its ``url`` and overrides of its own, such as the title of one video."""
    found = []
    for category, links in value.items():
        links = links if isinstance(links, list) else [links]
        urls = (link.get("url") if isinstance(link, Mapping) else link for link in links)
        found.append((str(category), tuple(str(url) for url in urls if isinstance(url, str) and url)))
    return tuple(found)


def _subscriptions(
    tree: Mapping, presets: _Presets, inherited: tuple[str, ...], indents: tuple[str, ...], global_presets: list[str],
) -> list[tuple[str, list[str], dict, list[str], Categories | None]]:
    """Each subscription under ``tree`` as (name, presets, own config, URLs, the categories of a map or None)."""
    found: list[tuple[str, list[str], dict, list[str], Categories | None]] = []
    for key, value in tree.items():
        key = str(key)
        if isinstance(value, str):
            found.append((key, [*inherited, *global_presets],
                          {"overrides": {**_indent_overrides(indents), "subscription_value": value, "url": value}},
                          [value], None))
        elif isinstance(value, list):
            urls = [str(item) for item in value]
            overrides = {**_indent_overrides(indents), "subscription_value": urls[0] if urls else ""}
            overrides.update({("url" if index == 0 else f"url{index + 1}"): url for index, url in enumerate(urls)})
            found.append((key, [*inherited, *global_presets], {"overrides": overrides}, urls, None))
        elif isinstance(value, Mapping):
            if key.startswith("~"):
                overrides = {**_indent_overrides(indents), **{str(name): item for name, item in value.items()}}
                found.append((key[1:].strip(), [*inherited, *global_presets], {"overrides": overrides}, [], None))
            elif key.startswith("+"):
                categories = _categories(value)
                urls = [url for _category, links in categories for url in links]
                found.append((key[1:].strip(), [*inherited, *global_presets],
                              {"overrides": _indent_overrides(indents)}, urls, categories))
            elif (group := _group(key, presets)) is not None:
                names, more_indents = group
                found += _subscriptions(value, presets, (*inherited, *names), (*indents, *more_indents), global_presets)
            else:
                # A whole preset: its own presets first, then those of the keys above it.
                own = dict(value)
                parents = own.pop("preset", []) or []
                parents = [parents] if isinstance(parents, str) else [str(item) for item in parents]
                own["overrides"] = {**(own.get("overrides") or {}), **_indent_overrides(indents)}
                found.append((key, [*parents, *inherited, *global_presets], own, [], None))
        else:
            raise YtdlSubReadError(f"The subscription {key} is neither a link, a list nor settings")
    return found


def _group(key: str, presets: _Presets) -> tuple[list[str], list[str]] | None:
    """The presets and indent values a key such as ``Jellyfin TV Show by Date | = News`` names, or None."""
    names: list[str] = []
    indents: list[str] = []
    for part in (part.strip() for part in key.split("|")):
        if part.startswith("="):
            indents.append(part[1:].strip())
        elif presets.known(part):
            names.append(part)
        elif names or indents:
            raise YtdlSubReadError(f"'{part}' in '{key}' is not a preset that VODLoft knows")
        else:
            return None
    return (names, indents) if names or indents else None


def _urls(config: Mapping, listed: Sequence[str]) -> list[str]:
    if listed:
        return list(listed)
    overrides = config.get("overrides") or {}
    urls = [str(overrides[name]) for name in ("url", *(f"url{number}" for number in range(2, 101)))
            if isinstance(overrides.get(name), str) and overrides[name] and "{" not in overrides[name]]
    download = config.get("download")
    entries = download if isinstance(download, list) else [download] if download else []
    for entry in entries:
        url = entry.get("url") if isinstance(entry, Mapping) else entry
        if isinstance(url, str) and url and "{" not in url:
            urls.append(url)
    return urls


def read_ytdl_sub(subscriptions: Path, config: Path | None = None) -> YtdlSubData:
    """Read ``subscriptions.yaml``, with the custom presets of ``config.yaml`` when there is one."""
    custom: dict[str, Mapping] = {}
    if config is not None and config.is_file():
        loaded = _load(config).get("presets") or {}
        if not isinstance(loaded, Mapping):
            raise YtdlSubReadError("The presets in config.yaml are not a list of named presets")
        custom = {str(name): value for name, value in loaded.items() if isinstance(value, Mapping)}
    tree = _load(subscriptions)
    file_preset = tree.pop(FILE_PRESET, None)
    if file_preset is not None:
        if not isinstance(file_preset, Mapping):
            raise YtdlSubReadError(f"{FILE_PRESET} in subscriptions.yaml is not a preset")
        custom = {**custom, FILE_PRESET: file_preset}
    presets = _Presets(custom)
    global_presets = [FILE_PRESET] if file_preset is not None else []

    result: list[Subscription] = []
    for name, names, own, listed, categories in _subscriptions(tree, presets, (), (), global_presets):
        applied, unknown = presets.sequence(names)
        merged = merge(*(presets.config(preset) for preset in applied), own)
        urls = _urls(merged, listed)
        result.append(Subscription(
            name=name,
            presets=tuple(preset for preset in names if preset != FILE_PRESET),
            applied=tuple(applied),
            config=merged,
            urls=tuple(urls),
            unknown=tuple(unknown),
            map=categories is not None,
            categories=categories or (),
        ))
    return YtdlSubData(tuple(result), tuple(name for name in custom if name != FILE_PRESET))
