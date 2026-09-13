from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class YtDlpSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: dict[str, Any] = Field(default_factory=dict)


class SchedulerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    collection_sync_interval_minutes: int = Field(default=30, ge=1, le=10080)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///./data/vodloft.db"
    download_root: str = "/downloads"
    worker_threads: int = Field(default=3, ge=1, le=32)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    yt_dlp: YtDlpSettings = Field(default_factory=YtDlpSettings)


def _default_path() -> Path:
    return Path(os.environ.get("VODLOFT_CONFIG", "config/config.yml"))


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path) if path is not None else _default_path()
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

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
