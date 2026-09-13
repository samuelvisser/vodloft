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


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///./data/vodloft.db"
    download_root: str = "/downloads"
    worker_threads: int = Field(default=3, ge=1, le=32)
    yt_dlp: YtDlpSettings = Field(default_factory=YtDlpSettings)


def _default_path() -> Path:
    return Path(os.environ.get("VODLOFT_CONFIG", "config/config.yml"))


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path) if path is not None else _default_path()
    if not config_path.exists():
        return Settings()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
