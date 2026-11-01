from __future__ import annotations

from typing import Optional

from pydantic import Field

from backend.api.models.base import RequestBase, ResponseBase


class LoginInput(RequestBase):
    """Input for login endpoint"""

    username: Optional[str] = Field(
        default=None,
        description="Needed once user accounts are on; leave out to sign in with the environment password",
    )
    passwordHash: str


class AuthResponse(ResponseBase):
    """Response for authentication status"""

    authenticated: bool


class PasswordChangeInput(RequestBase):
    current_password_hash: str
    new_password_hash: str


class SourceLimitRead(ResponseBase):
    source_key: str
    domains: Optional[list[str]] = Field(description="Domains within the Source; null: all of them")


class AuthUserRead(ResponseBase):
    id: int
    username: str
    template_key: Optional[str]
    must_change_password: bool


class AuthMeRead(ResponseBase):
    """Who is signed in and what they may do."""

    accounts_enabled: bool
    recovery: bool = Field(description="Signed in with the environment password because no administrator can sign in")
    user: Optional[AuthUserRead]
    levels: dict[str, str] = Field(description="Level per area: none, view or manage")
    administrator: bool
    sources: Optional[list[SourceLimitRead]] = Field(description="The Sources this user may use; null: every Source")
    members_only: bool
    delete_files: bool
