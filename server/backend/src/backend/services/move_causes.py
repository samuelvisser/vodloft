"""Why a collection's downloads wait for its Move action: the setting changes that put them in another season.

A setting that decides where a collection's videos go can leave its downloaded ones in a season they no longer belong
in; they wait for the Move action, which renames their files. Wherever such a setting changes, its origin takes the
settings before the change (``settings_of``) and, once the change is made, ``note_move_causes`` stores on the
collection what changed while downloads wait. Changes before a Move add up: a setting keeps the value it had before
the first of them, and one changed back drops out. The Move dialog shows them, and the stored changes go once nothing
waits any more.

Downloads can also wait without a recorded change, such as after an older VODLoft placed them differently; the
collection then stores none, and the dialog says what its settings make its seasons instead.

A new origin is a ``MoveCauseOrigin`` with a reader in ``READERS``, and its words in the UI's Move dialog.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

from backend.db.models import Collection
from backend.types.link_season_types import CollectionKind, LinkSeasons
from backend.types.move_cause_types import MoveCause, MoveCauseOrigin, MoveCauseValue

Settings = dict[tuple[str, int | None], tuple[MoveCauseValue, str | None]]
"""An origin's settings of a collection: by the setting and the id of what it is about, its value and that thing's
title."""


def _seasons_settings(collection: Collection) -> Settings:
    """The Seasons dialog's settings that decide where the collection's videos go."""
    settings: Settings = {
        ("link_seasons", None): (collection.link_seasons, None),
        ("outside_videos", None): (collection.outside_videos, None),
        ("list_layout", None): (collection.list_layout, None),
        ("loose_videos", None): (collection.loose_videos, None),
        ("repeat_videos", None): (collection.repeat_videos, None),
    }
    if collection.kind == CollectionKind.CHANNEL.value:
        settings[("feeds", None)] = (list(collection.feeds) if collection.feeds is not None else None, None)
    if collection.link_seasons == LinkSeasons.ALL.value:
        # Every list is in, and each one is a season of its own or contents only, as the collection says.
        settings[("lists_as_seasons", None)] = ("season" if collection.lists_as_seasons else "contents", None)
    elif collection.link_seasons != LinkSeasons.OFF.value:
        # What each list is: off, a season of its own, or only adding its videos to the other seasons.
        chosen = collection.link_seasons == LinkSeasons.SELECTED.value
        for link in collection.lists:
            state = "off" if chosen and not link.enabled else "season" if link.as_season else "contents"
            settings[("list", link.id)] = (state, link.title)
    return settings


READERS: dict[MoveCauseOrigin, Callable[[Collection], Settings]] = {
    MoveCauseOrigin.SEASONS: _seasons_settings,
}


def settings_of(collection: Collection, origin: MoveCauseOrigin) -> Settings:
    """The origin's settings of the collection, as they are now: take them before changing them."""
    return READERS[origin](collection)


def move_causes(collection: Collection) -> list[MoveCause]:
    """The stored changes that put the collection's downloads in another season, in the order they were made."""
    return [
        MoveCause(**{**cause, "origin": MoveCauseOrigin(cause["origin"])}) for cause in collection.move_causes or ()
    ]


def note_move_causes(collection: Collection, origin: MoveCauseOrigin, before: Settings, *, waiting: bool) -> None:
    """Store what the origin's settings changed from ``before``, now that its change is made, while downloads wait
    for the Move action; with none waiting, nothing is stored.

    Runs in the write transaction of the change."""
    if not waiting:
        clear_move_causes(collection)
        return
    after = settings_of(collection, origin)
    causes = {cause.key: cause for cause in move_causes(collection)}
    for (setting, subject_id), (now, title) in after.items():
        key = (origin.value, setting, subject_id)
        earlier = causes.get(key)
        if earlier is None and (setting, subject_id) not in before:
            # Something new, such as a list found just now, changed nothing.
            continue
        was = earlier.before if earlier is not None else before[(setting, subject_id)][0]
        if was == now:
            causes.pop(key, None)
        else:
            causes[key] = MoveCause(origin, setting, was, now, subject_id, title)
    stored = [{**asdict(cause), "origin": cause.origin.value} for cause in causes.values()]
    if stored != (collection.move_causes or []):
        collection.move_causes = stored


def clear_move_causes(collection: Collection) -> bool:
    """Forget the changes once no download waits for the Move action. Returns whether there were any."""
    if not collection.move_causes:
        return False
    collection.move_causes = []
    return True


__all__ = ["READERS", "Settings", "clear_move_causes", "move_causes", "note_move_causes", "settings_of"]
