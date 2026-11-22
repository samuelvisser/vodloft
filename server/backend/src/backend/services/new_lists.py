"""What a channel collection does with the lists its channel adds later, such as a new playlist or album: one setting
for each type of list of its Site (see ``Site.types_of``). Most Sites have one type; SoundCloud keeps an account's
albums apart from its playlists, so a SoundCloud collection has a setting for each.

A collection keeps its settings in ``Collection.new_lists`` by type key. A type without a setting yet starts with its
default.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sources import SECTION_KIND_NAMES, Names, SectionKind, Site

from backend.services.errors import ServiceError
from backend.types.link_season_types import NewLinkSeasonAction


@dataclass(frozen=True)
class ListKind:
    """One type of list on one Site, as the settings show it."""

    key: str
    names: Names
    albums: bool = False
    """The type best describes an artist's albums."""


@dataclass(frozen=True)
class NewListSetting:
    """What happens with a new list of one type."""

    kind: ListKind
    action: str

    @property
    def key(self) -> str:
        return self.kind.key


def list_kinds(site: Site) -> list[ListKind]:
    """The types of list of the Site, in its order."""
    return [ListKind(type_.key, type_.names, type_.albums) for type_ in site.types_of(SectionKind.LIST)]


_ALBUM_NAMES = frozenset({"album", "albums"})


def album_kinds(kinds: Iterable[ListKind]) -> set[str]:
    """The keys of the types of one Site that best describe an artist's albums: the ones the Site says do, or, where
    it says none does and has more than one type, the ones called album. Empty when no type stands out, as on a Site
    with one type or with several of other names."""
    kinds = list(kinds)
    marked = {kind.key for kind in kinds if kind.albums}
    if marked or len(kinds) < 2:
        return marked
    return {kind.key for kind in kinds if {kind.key.lower(), kind.names.singular.lower(),
                                           kind.names.plural.lower()} & _ALBUM_NAMES}


def kinds_names(kinds: Iterable[ListKind]) -> Names:
    """The types named together, such as "albums and playlists"; VODLoft's own word for lists when there are none."""
    kinds = list(kinds)
    return Names.joined(dict.fromkeys(kind.names for kind in kinds)) if kinds else SECTION_KIND_NAMES[SectionKind.LIST]


def default_new_link_seasons(kinds: Iterable[ListKind]) -> dict[str, str]:
    """What a collection does with each kind of new list until the user chooses: add it as a season, except that on a
    Site where some kinds best describe albums (``album_kinds``), such as SoundCloud, the others, its playlists, are
    left off."""
    kinds = list(kinds)
    albums = album_kinds(kinds)
    return {
        kind.key: (NewLinkSeasonAction.IGNORE if albums and kind.key not in albums else NewLinkSeasonAction.ADD).value
        for kind in kinds
    }


def new_link_seasons_settings(kinds: Iterable[ListKind], stored: Mapping[str, str] | None) -> list[NewListSetting]:
    """A collection's setting for each kind of its Site's lists: the one stored, or the kind's default."""
    kinds = list(kinds)
    defaults = default_new_link_seasons(kinds)
    return [NewListSetting(kind, (stored or {}).get(kind.key) or defaults[kind.key]) for kind in kinds]


def checked_new_link_seasons(kinds: Iterable[ListKind], wanted: Mapping[str, str]) -> dict[str, str]:
    """Every kind's setting for a collection, ``wanted`` over the defaults. Refuses a kind its Site doesn't have."""
    kinds = list(kinds)
    unknown = sorted(set(wanted) - {kind.key for kind in kinds})
    if unknown:
        raise ServiceError(f"This collection's site has no lists of the kind {unknown[0]}", field="new_lists")
    settings = default_new_link_seasons(kinds)
    return {key: NewLinkSeasonAction(wanted.get(key, action)).value for key, action in settings.items()}
