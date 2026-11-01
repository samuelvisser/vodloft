"""What the person behind a request may see and change.

VODLoft runs in one of two modes. Without user accounts there is one shared
password (or none), and whoever is signed in may do everything: ``Access.full()``
stands in for the missing user, so every check passes and the code paths stay
those of a single-user install. With user accounts on, each user has one level
per :class:`Area`, optional limits on the Sources and domains they may use, and
two switches that no level covers.

Levels are ordered: ``none`` < ``view`` < ``manage``. Each area only offers the
levels that mean something for it; the interface names them per area ("Use",
"Own", "Everyone's"), the stored value is always one of the three.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Optional


class Area(StrEnum):
    LIBRARY = "library"
    ADD_MEDIA = "add_media"
    MANAGED_DOWNLOADS = "managed_downloads"
    QUICK_DOWNLOADS = "quick_downloads"
    DOWNLOAD_PROFILES = "download_profiles"
    LOCAL_MEDIA_PROFILES = "local_media_profiles"
    STREAM_PROFILES = "stream_profiles"
    TASKS = "tasks"
    LOGS = "logs"
    SETTINGS = "settings"
    SOURCES = "sources"
    USERS = "users"


class Level(StrEnum):
    NONE = "none"
    VIEW = "view"
    MANAGE = "manage"

    @property
    def rank(self) -> int:
        return _LEVEL_RANK[self]


_LEVEL_RANK = {Level.NONE: 0, Level.VIEW: 1, Level.MANAGE: 2}

# The levels each area offers, lowest first.
AREA_LEVELS: Mapping[Area, tuple[Level, ...]] = MappingProxyType({
    Area.LIBRARY: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.ADD_MEDIA: (Level.NONE, Level.VIEW),
    Area.MANAGED_DOWNLOADS: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.QUICK_DOWNLOADS: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.DOWNLOAD_PROFILES: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.LOCAL_MEDIA_PROFILES: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.STREAM_PROFILES: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.TASKS: (Level.NONE, Level.VIEW, Level.MANAGE),
    Area.LOGS: (Level.NONE, Level.VIEW),
    Area.SETTINGS: (Level.NONE, Level.MANAGE),
    Area.SOURCES: (Level.NONE, Level.MANAGE),
    Area.USERS: (Level.NONE, Level.MANAGE),
})


def highest_level(area: Area) -> Level:
    return AREA_LEVELS[area][-1]


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    levels: Mapping[Area, Level]
    delete_files: bool = False


def _levels(**levels: Level) -> Mapping[Area, Level]:
    resolved = {area: Level.NONE for area in Area}
    resolved.update({Area(name): level for name, level in levels.items()})
    return MappingProxyType(resolved)


TEMPLATES: Mapping[str, Template] = MappingProxyType({
    template.key: template
    for template in (
        Template(
            key="administrator",
            name="Administrator",
            levels=MappingProxyType({area: highest_level(area) for area in Area}),
            delete_files=True,
        ),
        Template(
            key="library_manager",
            name="Library manager",
            levels=_levels(
                library=Level.MANAGE,
                add_media=Level.VIEW,
                managed_downloads=Level.MANAGE,
                quick_downloads=Level.VIEW,
                download_profiles=Level.VIEW,
                local_media_profiles=Level.VIEW,
                stream_profiles=Level.VIEW,
                tasks=Level.VIEW,
            ),
        ),
        Template(
            key="viewer",
            name="Viewer",
            levels=_levels(
                library=Level.VIEW,
                managed_downloads=Level.VIEW,
                stream_profiles=Level.VIEW,
            ),
        ),
        Template(
            key="downloader",
            name="Downloader",
            levels=_levels(quick_downloads=Level.VIEW),
        ),
    )
})

ADMINISTRATOR_TEMPLATE = "administrator"


def is_administrator_levels(levels: Mapping[Area, Level]) -> bool:
    """A user who may manage users can give themselves everything, so they get everything."""
    return levels.get(Area.USERS, Level.NONE) is Level.MANAGE


@dataclass(frozen=True)
class SourceLimit:
    """One Source a limited user may use, and the domains within it (``None``: all of them)."""

    source_key: str
    domains: Optional[tuple[str, ...]] = None


@dataclass(frozen=True)
class Access:
    """The resolved access of whoever is behind one request."""

    levels: Mapping[Area, Level]
    user_id: Optional[int] = None
    username: Optional[str] = None
    # ``None``: every Source. Otherwise only the listed ones.
    source_limits: Optional[Mapping[str, SourceLimit]] = None
    members_only: bool = True
    delete_files: bool = True
    must_change_password: bool = False
    # Signed in with the environment password while no administrator can sign in.
    recovery: bool = False
    template_key: Optional[str] = None
    session_version: int = 0

    @classmethod
    def full(cls, *, recovery: bool = False) -> "Access":
        """Everything, as in an install without user accounts."""
        return cls(
            levels=TEMPLATES[ADMINISTRATOR_TEMPLATE].levels,
            recovery=recovery,
            template_key=ADMINISTRATOR_TEMPLATE,
        )

    @classmethod
    def for_user(
        cls,
        *,
        user_id: int,
        username: str,
        levels: Mapping[Area, Level],
        source_limits: Optional[Mapping[str, SourceLimit]],
        members_only: bool,
        delete_files: bool,
        must_change_password: bool,
        template_key: Optional[str],
        session_version: int,
    ) -> "Access":
        resolved = {area: levels.get(area, Level.NONE) for area in Area}
        if is_administrator_levels(resolved):
            resolved = dict(TEMPLATES[ADMINISTRATOR_TEMPLATE].levels)
            source_limits = None
            members_only = True
            delete_files = True
        return cls(
            levels=MappingProxyType(resolved),
            user_id=user_id,
            username=username,
            source_limits=None if source_limits is None else MappingProxyType(dict(source_limits)),
            members_only=members_only,
            delete_files=delete_files,
            must_change_password=must_change_password,
            template_key=template_key,
            session_version=session_version,
        )

    @property
    def is_user(self) -> bool:
        return self.user_id is not None

    @property
    def is_administrator(self) -> bool:
        return is_administrator_levels(self.levels)

    def level(self, area: Area) -> Level:
        return self.levels.get(area, Level.NONE)

    def allows(self, area: Area, level: Level = Level.VIEW) -> bool:
        return self.level(area).rank >= level.rank

    def allows_source(self, source_key: str) -> bool:
        return self.source_limits is None or source_key in self.source_limits

    def allowed_domains(self, source_key: str) -> Optional[tuple[str, ...]]:
        """Domains this user may use on a Source; ``None`` when the Source has no domain limit."""
        if self.source_limits is None:
            return None
        limit = self.source_limits.get(source_key)
        return None if limit is None else limit.domains
