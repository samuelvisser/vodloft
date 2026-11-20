"""What happens with the lists a creator adds later, such as a new playlist or album: one setting for each type of
list and show on each of the creator's Sites (see ``Site.growing_types``). Most Sites have one type; SoundCloud keeps
an artist's albums apart from their playlists, so a SoundCloud artist has a setting for each.

A creator keeps its settings in ``Creator.new_lists`` by Site and type key, as ``{site: {type: action}}``, as type keys
are only unique within a Site. A collection is on one Site, and keeps its settings in ``Collection.new_lists`` by type
key alone. A type without a setting yet, such as one of a Site an account joined from later, starts with its default.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sources import SECTION_KIND_NAMES, Names, SectionKind, Site

from backend.services.errors import ServiceError
from backend.types.creator_types import NewSectionAction
from backend.types.link_season_types import NewLinkSeasonAction

SiteSettings = Mapping[str, Mapping[str, str]]
"""Settings by Site key, then by type key."""


@dataclass(frozen=True)
class ListKind:
    """One type of list or show on one Site, as the settings show it."""

    site_key: str
    site_name: str
    key: str
    names: Names
    seasons: bool
    """The Site can make the lists seasons of the creator's own collection."""
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

    @property
    def site_key(self) -> str:
        return self.kind.site_key


def list_kinds(sites: Iterable[Site]) -> list[ListKind]:
    """The types of list and show of ``sites``, in their order, each Site's apart."""
    return [
        ListKind(site.key, site.name, type_.key, type_.names, site.link_seasons and type_.kind is SectionKind.LIST, type_.albums)
        for site in sites for type_ in site.growing_types
    ]


def _by_site(kinds: Iterable[ListKind]) -> dict[str, list[ListKind]]:
    sites: dict[str, list[ListKind]] = {}
    for kind in kinds:
        sites.setdefault(kind.site_key, []).append(kind)
    return sites


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


def _default_new_sections(kinds: list[ListKind], music: bool) -> dict[str, str]:
    """What a new creator does with each type of new list of one Site. An artist adds them to their own collection,
    as albums; where some types best describe albums (``album_kinds``), only those, and skips the others. Anyone else
    is asked."""
    albums = album_kinds(kinds)

    def action(kind: ListKind) -> NewSectionAction:
        if not music or not kind.seasons:
            return NewSectionAction.ASK
        return NewSectionAction.SEASON if kind.key in albums or not albums else NewSectionAction.IGNORE

    return {kind.key: action(kind).value for kind in kinds}


def default_new_sections(kinds: Iterable[ListKind], music: bool) -> dict[str, dict[str, str]]:
    """What a new creator does with each type of new list, by Site."""
    return {site: _default_new_sections(site_kinds, music) for site, site_kinds in _by_site(kinds).items()}


def kinds_names(kinds: Iterable[ListKind]) -> Names:
    """The types named together, such as "albums and playlists"; VODLoft's own word for lists when there are none.
    Sites that share a type, such as YouTube's and Floatplane's playlists, name it once."""
    kinds = list(kinds)
    return Names.joined(dict.fromkeys(kind.names for kind in kinds)) if kinds else SECTION_KIND_NAMES[SectionKind.LIST]


def new_sections_settings(kinds: Iterable[ListKind], stored: SiteSettings | None, music: bool) -> list[NewListSetting]:
    """The creator's setting for each type: the one stored, or the type's default."""
    kinds = list(kinds)
    defaults = default_new_sections(kinds, music)
    stored = stored or {}
    return [
        NewListSetting(kind, stored.get(kind.site_key, {}).get(kind.key) or defaults[kind.site_key][kind.key])
        for kind in kinds
    ]


def checked_new_sections(kinds: Iterable[ListKind], wanted: SiteSettings, music: bool) -> dict[str, dict[str, str]]:
    """Every type's setting, ``wanted`` over the defaults, by Site. Refuses a type the Sites don't have, and adding to
    the creator's own collection for a type whose lists can't be seasons there, such as The Daily Wire's shows."""
    kinds = list(kinds)
    known = {(kind.site_key, kind.key): kind for kind in kinds}
    settings = default_new_sections(kinds, music)
    for site_key, actions in wanted.items():
        for key, action in actions.items():
            kind = known.get((site_key, key))
            if kind is None:
                raise ServiceError(f"This creator's sites have no lists of the kind {key} on {site_key}", field="new_lists")
            if NewSectionAction(action) in (NewSectionAction.SEASON, NewSectionAction.LOOSE) and not kind.seasons:
                raise ServiceError(f"New {kind.names.plural} can't be added as seasons", field="new_lists")
            settings[site_key][key] = NewSectionAction(action).value
    return settings


def merged_settings(current: SiteSettings, wanted: SiteSettings) -> dict[str, dict[str, str]]:
    """``wanted`` over ``current``, Site by Site."""
    merged = {site: dict(actions) for site, actions in current.items()}
    for site, actions in wanted.items():
        merged.setdefault(site, {}).update(actions)
    return merged


def site_settings(settings: Iterable[NewListSetting], site_key: str) -> dict[str, str]:
    """The settings of one Site, by type key."""
    return {setting.key: setting.action for setting in settings if setting.site_key == site_key}


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


def skipped_kinds(site: Site, music: bool) -> set[str]:
    """The keys of the types of ``site`` a new creator skips by default, such as a SoundCloud artist's playlists."""
    defaults = _default_new_sections(list_kinds([site]), music)
    return {key for key, action in defaults.items() if action == NewSectionAction.IGNORE.value}
