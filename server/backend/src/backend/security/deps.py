"""Declaring what access an API route needs.

Every API router declares a requirement with ``requires(...)``, either for
the whole router or per route. ``tests/unit/test_route_access.py`` fails for
an /api route that declares none, so a new route cannot be left open by
accident.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from .access import Access, Area, Level
from .auth import request_access


NOT_ALLOWED = "You don't have access to this part of VODLoft."


class AccessRequirement:
    """A FastAPI dependency that refuses requests without the given level for an area."""

    def __init__(self, area: Area, level: Level) -> None:
        self.area = area
        self.level = level

    def __call__(self, request: Request) -> Access:
        access = request_access(request)
        if not access.allows(self.area, self.level):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ALLOWED)
        return access

    def __repr__(self) -> str:
        return f"requires({self.area.value}, {self.level.value})"


class AnyAccessRequirement:
    """Passes when the request has at least one of several area levels.

    For data that more than one part of VODLoft needs, such as the profile
    lists the Add show wizard offers.
    """

    def __init__(self, *requirements: tuple[Area, Level]) -> None:
        self.requirements = requirements

    def __call__(self, request: Request) -> Access:
        access = request_access(request)
        if not any(access.allows(area, level) for area, level in self.requirements):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NOT_ALLOWED)
        return access

    def __repr__(self) -> str:
        return "requires_any(" + ", ".join(f"{a.value}:{l.value}" for a, l in self.requirements) + ")"


class DeleteFilesRequirement:
    """Deleting downloaded files from disk is its own switch, on top of the area level."""

    def __call__(self, request: Request) -> Access:
        access = request_access(request)
        if not access.delete_files:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may not delete downloaded files from disk.",
            )
        return access

    def __repr__(self) -> str:
        return "may_delete_files()"


class SignedIn:
    """For routes every signed-in person may use, whatever their access."""

    def __call__(self, request: Request) -> Access:
        return request_access(request)

    def __repr__(self) -> str:
        return "signed_in()"


def requires(area: Area, level: Level = Level.VIEW):
    return Depends(AccessRequirement(area, level))


def requires_any(*requirements: tuple[Area, Level]):
    return Depends(AnyAccessRequirement(*requirements))


def may_delete_files():
    return Depends(DeleteFilesRequirement())


def signed_in():
    return Depends(SignedIn())


def is_access_dependency(dependency: Callable) -> bool:
    return isinstance(dependency, (AccessRequirement, AnyAccessRequirement, SignedIn))
