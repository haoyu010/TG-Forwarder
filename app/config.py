from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    source_channels: list[str] = field(default_factory=list)
    target_channel: str = ""
    session_path: str = "data/session/tg-forwarder"


@dataclass(frozen=True)
class TmdbConfig:
    api_key: str
    language: str = "zh-CN"
    fallback_language: str = "en-US"


@dataclass(frozen=True)
class FilterSettings:
    blacklist_genres: list[str] = field(default_factory=list)
    blacklist_genre_ids: list[int] = field(default_factory=list)
    blacklist_region_categories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    tmdb: TmdbConfig
    filters: FilterSettings = field(default_factory=FilterSettings)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    database_path: str = "data/forwarder.sqlite3"


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    raw = _read_yaml(path)
    telegram = raw.get("telegram", {})
    tmdb = raw.get("tmdb", {})
    filters = raw.get("filters", {})
    dashboard = raw.get("dashboard", {})

    api_id = _optional_int(os.getenv("TELEGRAM_API_ID"), telegram.get("api_id", 0))
    api_hash = _optional_str(os.getenv("TELEGRAM_API_HASH"), telegram.get("api_hash", ""))
    tmdb_api_key = _optional_str(os.getenv("TMDB_API_KEY"), tmdb.get("api_key", ""))

    return AppConfig(
        telegram=TelegramConfig(
            api_id=api_id,
            api_hash=api_hash,
            source_channels=[str(channel) for channel in telegram.get("source_channels", [])],
            target_channel=str(telegram.get("target_channel", "")),
            session_path=str(telegram.get("session_path", "data/session/tg-forwarder")),
        ),
        tmdb=TmdbConfig(
            api_key=tmdb_api_key,
            language=str(tmdb.get("language", "zh-CN")),
            fallback_language=str(tmdb.get("fallback_language", "en-US")),
        ),
        filters=FilterSettings(
            blacklist_genres=[str(name) for name in filters.get("blacklist_genres", [])],
            blacklist_genre_ids=[int(genre_id) for genre_id in filters.get("blacklist_genre_ids", [])],
            blacklist_region_categories=[str(name) for name in filters.get("blacklist_region_categories", [])],
        ),
        dashboard=DashboardConfig(
            host=str(dashboard.get("host", "0.0.0.0")),
            port=int(dashboard.get("port", 8000)),
        ),
        database_path=str(raw.get("database_path", "data/forwarder.sqlite3")),
    )


def _read_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a mapping at the top level")
    return data


def _optional_str(env_value: str | None, fallback: Any) -> str:
    if env_value is not None and env_value != "":
        return str(env_value)
    return str(fallback or "")


def _optional_int(env_value: str | None, fallback: Any) -> int:
    value = env_value if env_value not in {None, ""} else fallback
    if value in {None, ""}:
        return 0
    return int(value)
