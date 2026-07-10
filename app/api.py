from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import yaml

from app.config import AppConfig, FilterSettings, TelegramConfig, load_config
from app.runtime import build_worker, can_build_worker, session_exists
from app.storage import EventRepository
from app.telegram_login import TelegramLoginManager


class TelegramSettingsPayload(BaseModel):
    source_channels: list[str] = Field(default_factory=list)
    target_channel: str = ""


class FilterSettingsPayload(BaseModel):
    blacklist_genres: list[str] = Field(default_factory=list)
    blacklist_genre_ids: list[int] = Field(default_factory=list)
    blacklist_region_categories: list[str] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    telegram: TelegramSettingsPayload
    filters: FilterSettingsPayload


class SendCodePayload(BaseModel):
    phone: str


class SignInPayload(BaseModel):
    code: str
    password: str | None = None


def create_app(
    config: AppConfig | None = None,
    repository: EventRepository | None = None,
    worker: Any | None = None,
    config_path: str | Path = "config.yaml",
) -> FastAPI:
    app_config = config or load_config()
    repo = repository or EventRepository(app_config.database_path)
    config_file = Path(config_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await repo.initialize()
        if app.state.worker and hasattr(app.state.worker, "start"):
            await app.state.worker.start()
        yield
        if app.state.worker and hasattr(app.state.worker, "stop"):
            await app.state.worker.stop()

    app = FastAPI(title="TG TMDB Forwarder", lifespan=lifespan)
    app.state.config = app_config
    app.state.repository = repo
    app.state.worker = worker
    app.state.login_manager = TelegramLoginManager(app_config.telegram)

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        current_config: AppConfig = app.state.config
        stats = await repo.stats_today()
        current_worker = app.state.worker
        running = bool(getattr(current_worker, "running", False)) if current_worker else False
        return {
            "worker": {
                "running": running,
                "can_start": can_build_worker(current_config),
                "session_exists": session_exists(current_config),
            },
            "telegram": {
                "configured": bool(current_config.telegram.api_id and current_config.telegram.api_hash),
                "source_count": len(current_config.telegram.source_channels),
                "target_channel": current_config.telegram.target_channel,
            },
            "tmdb": {"configured": bool(current_config.tmdb.api_key), "language": current_config.tmdb.language},
            "stats": stats,
        }

    @app.get("/api/records")
    async def records(limit: int = 100) -> dict[str, Any]:
        events = await repo.list_events(limit=limit)
        return {
            "items": [
                {
                    "id": event.id,
                    "telegram_message_id": event.telegram_message_id,
                    "source_channel": event.source_channel,
                    "title": event.title,
                    "tmdb_id": event.tmdb_id,
                    "tmdb_media_type": event.tmdb_media_type,
                    "tmdb_title": event.tmdb_title,
                    "tmdb_year": event.tmdb_year,
                    "region_category": event.region_category,
                    "genres": json.loads(event.genres_json),
                    "genre_ids": json.loads(event.genre_ids_json),
                    "decision": event.decision,
                    "reason": event.reason,
                    "created_at": event.created_at.isoformat(),
                }
                for event in events
            ]
        }

    @app.get("/api/settings")
    async def settings() -> dict[str, Any]:
        current_config: AppConfig = app.state.config
        return {
            "telegram": {
                "source_channels": current_config.telegram.source_channels,
                "target_channel": current_config.telegram.target_channel,
            },
            "filters": {
                "blacklist_genres": current_config.filters.blacklist_genres,
                "blacklist_genre_ids": current_config.filters.blacklist_genre_ids,
                "blacklist_region_categories": current_config.filters.blacklist_region_categories,
            },
        }

    @app.put("/api/settings")
    async def update_settings(payload: SettingsPayload) -> dict[str, Any]:
        current_config: AppConfig = app.state.config
        source_channels = [channel.strip() for channel in payload.telegram.source_channels if channel.strip()]
        target_channel = payload.telegram.target_channel.strip()
        blacklist_genres = [genre.strip() for genre in payload.filters.blacklist_genres if genre.strip()]
        blacklist_genre_ids = payload.filters.blacklist_genre_ids
        blacklist_region_categories = [name.strip() for name in payload.filters.blacklist_region_categories if name.strip()]

        next_config = replace(
            current_config,
            telegram=replace(
                current_config.telegram,
                source_channels=source_channels,
                target_channel=target_channel,
            ),
            filters=FilterSettings(
                blacklist_genres=blacklist_genres,
                blacklist_genre_ids=blacklist_genre_ids,
                blacklist_region_categories=blacklist_region_categories,
            ),
        )
        _write_runtime_config(config_file, next_config)
        app.state.config = next_config
        app.state.login_manager = TelegramLoginManager(next_config.telegram)
        current_worker = app.state.worker
        if current_worker and hasattr(current_worker, "apply_runtime_settings"):
            current_worker.apply_runtime_settings(next_config.filters, next_config.telegram.target_channel)
        return await settings()

    @app.post("/api/worker/start")
    async def start_worker() -> dict[str, Any]:
        current_config: AppConfig = app.state.config
        current_worker = app.state.worker
        if current_worker and getattr(current_worker, "running", False):
            return {"running": True, "message": "监听服务已经在运行"}
        next_worker = build_worker(current_config, repo)
        if not next_worker:
            return {
                "running": False,
                "message": "还不能启动：请确认已登录 Telegram、源频道/目标频道/TMDB 已配置",
            }
        app.state.worker = next_worker
        await next_worker.start()
        return {"running": True, "message": "监听服务已启动"}

    @app.post("/api/worker/stop")
    async def stop_worker() -> dict[str, Any]:
        current_worker = app.state.worker
        if current_worker and hasattr(current_worker, "stop"):
            await current_worker.stop()
        app.state.worker = None
        return {"running": False, "message": "监听服务已停止"}

    @app.post("/api/worker/restart")
    async def restart_worker() -> dict[str, Any]:
        await stop_worker()
        return await start_worker()

    @app.post("/api/worker/test-forward")
    async def test_forward_latest() -> dict[str, Any]:
        current_worker = app.state.worker
        if not current_worker or not getattr(current_worker, "running", False):
            result = await start_worker()
            if not result.get("running"):
                return result
            current_worker = app.state.worker
        message = await current_worker.process_latest_message()
        return {"running": True, "message": message}

    @app.get("/api/telegram-login")
    async def telegram_login_status() -> dict[str, str]:
        manager: TelegramLoginManager = app.state.login_manager
        return {"status": manager.state.status, "message": manager.state.message}

    @app.post("/api/telegram-login/send-code")
    async def telegram_send_code(payload: SendCodePayload) -> dict[str, str]:
        manager: TelegramLoginManager = app.state.login_manager
        state = await manager.send_code(payload.phone.strip())
        return {"status": state.status, "message": state.message}

    @app.post("/api/telegram-login/sign-in")
    async def telegram_sign_in(payload: SignInPayload) -> dict[str, str]:
        manager: TelegramLoginManager = app.state.login_manager
        state = await manager.sign_in(payload.code.strip(), payload.password)
        message = state.message
        if state.status == "signed_in":
            try:
                result = await restart_worker()
                message = f"{message}；{result['message']}"
            except Exception as exc:
                message = f"{message}；监听服务启动失败：{exc}"
        return {"status": state.status, "message": message}

    static_dir = Path("web/dist")
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            target = static_dir / path
            if path and target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(static_dir / "index.html")

    return app


def _write_runtime_config(path: Path, config: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "database_path": config.database_path,
        "telegram": {
            "source_channels": config.telegram.source_channels,
            "target_channel": config.telegram.target_channel,
            "session_path": config.telegram.session_path,
        },
        "tmdb": {
            "language": config.tmdb.language,
            "fallback_language": config.tmdb.fallback_language,
        },
        "filters": {
            "blacklist_genres": config.filters.blacklist_genres,
            "blacklist_genre_ids": config.filters.blacklist_genre_ids,
            "blacklist_region_categories": config.filters.blacklist_region_categories,
        },
        "dashboard": {
            "host": config.dashboard.host,
            "port": config.dashboard.port,
        },
    }
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
