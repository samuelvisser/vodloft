from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class YtDlpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    options: dict[str, Any] = Field(default_factory=dict)


class SchedulerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    collection_sync_interval_minutes: int = Field(default=30, ge=1, le=10080)
    verification_interval_minutes: int = Field(default=120, ge=5, le=10080)


class TaskManagerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_max_retries: int = Field(default=3, ge=0, le=20)
    retry_backoff_base_seconds: int = Field(default=5, ge=1, le=3600)
    retry_backoff_max_seconds: int = Field(default=300, ge=1, le=86400)
    stalled_timeout_minutes: int = Field(default=20, ge=5, le=1440)
    download_max_concurrency: int = Field(default=3, ge=1, le=32)

    @model_validator(mode="after")
    def validate_backoff(self):
        if self.retry_backoff_max_seconds < self.retry_backoff_base_seconds:
            raise ValueError("retry_backoff_max_seconds must be greater than or equal to retry_backoff_base_seconds")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///./data/vodloft.db"
    download_root: str = "/downloads"
    worker_threads: int = Field(default=5, ge=1, le=32)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    task_manager: TaskManagerSettings = Field(default_factory=TaskManagerSettings)
    yt_dlp: YtDlpSettings = Field(default_factory=YtDlpSettings)


def config_path() -> Path:
    return Path(os.environ.get("VODLOFT_CONFIG", "config/config.yml"))


def load_settings(path: str | Path | None = None) -> Settings:
    target = Path(path) if path is not None else config_path()
    raw: dict[str, Any] = {}
    if target.exists():
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    if database_url := os.environ.get("VODLOFT_DATABASE_URL"):
        raw["database_url"] = database_url
    if download_root := os.environ.get("VODLOFT_DOWNLOAD_ROOT"):
        raw["download_root"] = download_root
    if worker_threads := os.environ.get("VODLOFT_WORKER_THREADS"):
        raw["worker_threads"] = int(worker_threads)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def save_settings(settings: Settings, path: str | Path | None = None) -> Settings:
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(
        settings.model_dump(mode="python"),
        sort_keys=False,
        allow_unicode=True,
    )
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(target)
    if path is None:
        return reload_settings()
    return load_settings(target)


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
