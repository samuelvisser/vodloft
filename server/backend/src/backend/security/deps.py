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


class SignedIn:
    """For routes every signed-in person may use, whatever their access."""

    def __call__(self, request: Request) -> Access:
        return request_access(request)

    def __repr__(self) -> str:
        return "signed_in()"


def requires(area: Area, level: Level = Level.VIEW):
    return Depends(AccessRequirement(area, level))


def signed_in():
    return Depends(SignedIn())


def access_dependency_of(dependency: Callable) -> bool:
    return isinstance(dependency, (AccessRequirement, SignedIn))
