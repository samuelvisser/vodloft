from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from backend.api.models.auth import SourceLimitRead
from backend.api.models.base import RequestBase, ResponseBase


class SourceLimitInput(RequestBase):
    source_key: str
    domains: Optional[list[str]] = Field(default=None, description="null: all of the Source's domains")


class UserAccessInput(RequestBase):
    """A user's access list as the user editor sends it."""

    template_key: Optional[str] = Field(default=None, description="The template it was filled in from, while it still matches")
    levels: dict[str, str] = Field(description="Level per area: none, view or manage. Missing areas are none")
    sources: Optional[list[SourceLimitInput]] = Field(default=None, description="null: every Source")
    members_only: bool = False
    delete_files: bool = False


class UserCreate(RequestBase):
    username: str
    password_hash: str = Field(description="The value the browser derives from the first password")
    access: UserAccessInput


class UserUpdate(RequestBase):
    username: Optional[str] = None
    enabled: Optional[bool] = None
    access: Optional[UserAccessInput] = None


class UserPasswordReset(RequestBase):
    password_hash: str = Field(description="A one-time password the user must change at their next sign-in")


class UserRead(ResponseBase):
    id: int
    username: str
    enabled: bool
    must_change_password: bool
    template_key: Optional[str]
    administrator: bool
    levels: dict[str, str]
    sources: Optional[list[SourceLimitRead]]
    members_only: bool
    delete_files: bool
    created_by: Optional[str] = Field(description="Username of the administrator who created this user")
    created_at: datetime
    last_login_at: Optional[datetime]


class FirstAdministratorInput(RequestBase):
    username: str
    password_hash: str


class UserAccountsSettingsRead(ResponseBase):
    enabled: bool
    environment_password: bool = Field(description="Whether VL_ADMIN_AUTH__PASSWORD is set, for recovery")
    administrators: int = Field(description="Enabled administrators")


class UserAccountsSettingsUpdate(RequestBase):
    enabled: bool
    first_administrator: Optional[FirstAdministratorInput] = Field(
        default=None, description="Needed to turn accounts on while there is no administrator yet",
    )


class AccessTemplateRead(ResponseBase):
    key: str
    name: str
    levels: dict[str, str]
    delete_files: bool


class AccessAreaRead(ResponseBase):
    area: str
    levels: list[str]


class AccessOptionsRead(ResponseBase):
    """The areas, their levels and the templates the user editor offers."""

    areas: list[AccessAreaRead]
    templates: list[AccessTemplateRead]
