"""What happens with the lists a creator adds later, such as a new playlist or album: one setting for each kind of
list the creator's Sites have (see ``Site.kinds_of_list``). Most Sites have one kind; SoundCloud keeps an artist's
albums apart from their playlists, so a SoundCloud artist has a setting for each.

A creator keeps its settings in ``Creator.new_lists`` and a collection in ``Collection.new_lists``, by the kind's
key. A kind without a setting yet, such as one of a Site an account joined from later, starts with its default.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sources import CreatorSectionNames, SectionRef, Site

from backend.services.errors import ServiceError
from backend.types.creator_types import NewSectionAction
from backend.types.link_season_types import NewLinkSeasonAction


@dataclass(frozen=True)
class ListKind:
    """One kind of list a creator's Sites have, as the settings show it."""

    key: str
    names: CreatorSectionNames
    seasons: bool
    """One of these Sites can make the lists seasons of the creator's own collection."""
    albums: bool = False
    """The kind best describes an artist's albums."""


@dataclass(frozen=True)
class NewListSetting:
    """What happens with a new list of one kind."""

    kind: ListKind
    action: str

    @property
    def key(self) -> str:
        return self.kind.key

    @property
    def one(self) -> str:
        return self.kind.names.one

    @property
    def many(self) -> str:
        return self.kind.names.many

    @property
    def seasons(self) -> bool:
        return self.kind.seasons


def list_kinds(sites: Iterable[Site]) -> list[ListKind]:
    """The kinds of list of ``sites``, in their order. Sites that share a kind, such as YouTube's and The Daily Wire's
    one kind, share its setting, named for all of them."""
    kinds: dict[str, ListKind] = {}
    for site in sites:
        for kind in site.kinds_of_list:
            known = kinds.get(kind.key)
            if known is None:
                kinds[kind.key] = ListKind(kind.key, kind.names, site.link_seasons, kind.albums)
            else:
                names = known.names if known.names == kind.names else CreatorSectionNames()
                kinds[kind.key] = ListKind(kind.key, names, known.seasons or site.link_seasons, known.albums or kind.albums)
    return list(kinds.values())


_ALBUM_NAMES = frozenset({"album", "albums"})


def album_kinds(kinds: Iterable[ListKind]) -> set[str]:
    """The keys of the kinds that best describe an artist's albums: the ones their Site says do, or, where it says
    none does and has more than one kind, the ones called album. Empty when no kind stands out, as on a Site with one
    kind or with several of other names."""
    kinds = list(kinds)
    marked = {kind.key for kind in kinds if kind.albums}
    if marked or len(kinds) < 2:
        return marked
    return {kind.key for kind in kinds if {kind.key.lower(), kind.names.one.lower().removeprefix("an "),
                                           kind.names.many.lower()} & _ALBUM_NAMES}


def default_new_sections(kinds: Iterable[ListKind], music: bool) -> dict[str, str]:
    """What a new creator does with each kind of new list. An artist adds them to their own collection, as albums;
    where some kinds best describe albums (``album_kinds``), only those, and skips the others. Anyone else is
    asked."""
    kinds = list(kinds)
    albums = album_kinds(kinds)

    def action(kind: ListKind) -> NewSectionAction:
        if not music or not kind.seasons:
            return NewSectionAction.ASK
        return NewSectionAction.SEASON if kind.key in albums or not albums else NewSectionAction.IGNORE

    return {kind.key: action(kind).value for kind in kinds}


def new_sections_settings(kinds: Iterable[ListKind], stored: Mapping[str, str] | None, music: bool) -> list[NewListSetting]:
    """The creator's setting for each kind: the one stored, or the kind's default."""
    kinds = list(kinds)
    defaults = default_new_sections(kinds, music)
    return [NewListSetting(kind, (stored or {}).get(kind.key) or defaults[kind.key]) for kind in kinds]


def checked_new_sections(kinds: Iterable[ListKind], wanted: Mapping[str, str], music: bool) -> dict[str, str]:
    """Every kind's setting, ``wanted`` over the defaults. Refuses a kind the Sites don't have, and "Add it as a season"
    for a kind whose lists can't be seasons, such as The Daily Wire's shows."""
    kinds = {kind.key: kind for kind in kinds}
    unknown = sorted(set(wanted) - set(kinds))
    if unknown:
        raise ServiceError(f"This creator's sites have no lists of the kind {unknown[0]}", field="new_lists")
    settings = default_new_sections(kinds.values(), music)
    for key, action in wanted.items():
        kind = kinds[key]
        if NewSectionAction(action) is NewSectionAction.SEASON and not kind.seasons:
            raise ServiceError(f"New {kind.names.many} can't be added as seasons", field="new_lists")
        settings[key] = NewSectionAction(action).value
    return settings


def section_kind(site: Site, section: SectionRef) -> str:
    """The key of the kind of list a section is on its Site."""
    return site.list_type_of(section).key


def link_season_action(action: str) -> NewLinkSeasonAction:
    """What a creator's own collection does with a new list, for what the creator does with it: the creator's daily
    look finds them and places them; the collection only follows."""
    match NewSectionAction(action):
        case NewSectionAction.ASK:
            return NewLinkSeasonAction.ASK
        case NewSectionAction.SEASON:
            return NewLinkSeasonAction.ADD
        case _:
            return NewLinkSeasonAction.IGNORE


def default_new_link_seasons(kinds: Iterable[ListKind], music: bool) -> dict[str, str]:
    """What a collection does with each kind of new list until the user chooses: ask, except that a Music
    collection on a Site where some kinds best describe albums (``album_kinds``) skips the others, such as SoundCloud
    playlists."""
    kinds = list(kinds)
    albums = album_kinds(kinds) if music else set()
    return {
        kind.key: (NewLinkSeasonAction.IGNORE if albums and kind.key not in albums else NewLinkSeasonAction.ASK).value
        for kind in kinds
    }


def new_link_seasons_settings(kinds: Iterable[ListKind], stored: Mapping[str, str] | None, music: bool) -> list[NewListSetting]:
    """A collection's setting for each kind of its Site's lists: the one stored, or the kind's default."""
    kinds = list(kinds)
    defaults = default_new_link_seasons(kinds, music)
    return [NewListSetting(kind, (stored or {}).get(kind.key) or defaults[kind.key]) for kind in kinds]


def checked_new_link_seasons(kinds: Iterable[ListKind], wanted: Mapping[str, str], music: bool) -> dict[str, str]:
    """Every kind's setting for a collection, ``wanted`` over the defaults. Refuses a kind its Site doesn't have."""
    kinds = list(kinds)
    unknown = sorted(set(wanted) - {kind.key for kind in kinds})
    if unknown:
        raise ServiceError(f"This collection's site has no lists of the kind {unknown[0]}", field="new_lists")
    settings = default_new_link_seasons(kinds, music)
    return {key: NewLinkSeasonAction(wanted.get(key, action)).value for key, action in settings.items()}


def skipped_kinds(kinds: Iterable[ListKind], music: bool) -> set[str]:
    """The kinds a new creator skips by default, such as a SoundCloud artist's playlists."""
    return {key for key, action in default_new_sections(kinds, music).items() if action == NewSectionAction.IGNORE.value}
