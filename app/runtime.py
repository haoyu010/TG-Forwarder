from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.storage import EventRepository
from app.telegram_worker import PipelineWorker, TelethonForwarderService, TelethonSender
from app.tmdb import TmdbClient


def session_exists(config: AppConfig) -> bool:
    return Path(config.telegram.session_path + ".session").exists()


def can_build_worker(config: AppConfig) -> bool:
    return bool(
        config.telegram.api_id
        and config.telegram.api_hash
        and config.tmdb.api_key
        and config.telegram.source_channels
        and config.telegram.target_channel
        and session_exists(config)
    )


def build_worker(config: AppConfig, repository: EventRepository) -> TelethonForwarderService | None:
    if not can_build_worker(config):
        return None

    pipeline = PipelineWorker(
        tmdb_client=TmdbClient(
            api_key=config.tmdb.api_key,
            language=config.tmdb.language,
            fallback_language=config.tmdb.fallback_language,
        ),
        sender=TelethonSender(),
        repository=repository,
        filters=config.filters,
        target_channel=config.telegram.target_channel,
    )
    return TelethonForwarderService(config.telegram, pipeline)
