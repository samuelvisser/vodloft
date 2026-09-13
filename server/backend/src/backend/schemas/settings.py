from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class AuthStatusRead(BaseModel):
    auth_enabled: bool
    setup_required: bool
    authenticated: bool
    username: str
    onboarding_completed: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str = "admin"
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class ApplicationSettingsRead(BaseModel):
    onboarding_completed: bool
    alembic_version_num: str | None
    auth_enabled: bool
    admin_username: str
    rss_token: str
    rss_item_limit: int
    worker_threads: int
    scheduler_enabled: bool
    collection_sync_interval_minutes: int
    verification_interval_minutes: int
    default_max_retries: int
    retry_backoff_base_seconds: int
    retry_backoff_max_seconds: int
    stalled_timeout_minutes: int
    download_max_concurrency: int
    yt_dlp_options: dict[str, Any]


class RuntimeSettingsUpdate(BaseModel):
    worker_threads: int | None = Field(default=None, ge=1, le=32)
    scheduler_enabled: bool | None = None
    collection_sync_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    verification_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    default_max_retries: int | None = Field(default=None, ge=0, le=20)
    retry_backoff_base_seconds: int | None = Field(default=None, ge=1, le=3600)
    retry_backoff_max_seconds: int | None = Field(default=None, ge=1, le=86400)
    stalled_timeout_minutes: int | None = Field(default=None, ge=5, le=1440)
    download_max_concurrency: int | None = Field(default=None, ge=1, le=32)
    yt_dlp_options: dict[str, Any] | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ApplicationSettingsUpdate(BaseModel):
    onboarding_completed: bool | None = None
    auth_enabled: bool | None = None
    admin_username: str | None = None
    rss_item_limit: int | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self
