from __future__ import annotations

from pydantic import Field

from backend.api.models.base import ResponseBase


class PublicSessionConfig(ResponseBase):
    ttl_seconds: int


class PublicAdminAuth(ResponseBase):
    enabled: bool = Field(description="Whether admin auth is enabled (derived from presence of a configured password hash)")


class PublicUserAccounts(ResponseBase):
    enabled: bool = Field(description="Whether everyone signs in with their own username and password")


class ConfigPublicRead(ResponseBase):
    app_version: str
    login_session: PublicSessionConfig
    admin_auth: PublicAdminAuth
    user_accounts: PublicUserAccounts
