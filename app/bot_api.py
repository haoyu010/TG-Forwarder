#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI dashboard + background bot loop for the bot forwarder.

Serves the original React dashboard on port 8000 (host 8001) and exposes the
same /api endpoints the frontend expects, backed by the bot's SQLite DB and
config.yaml filters.
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import web_forwarder as wf

TOKEN = wf.os.getenv("TELEGRAM_BOT_TOKEN", "")
CONFIG_PATH = Path(wf.os.getenv("CONFIG_PATH", "config.yaml"))
DIST = Path("web/dist")

stop_event = threading.Event()
loop_thread: threading.Thread | None = None
loop_lock = threading.Lock()
state: dict[str, Any] = {"running": False, "last_error": "", "last_run": ""}


class TelegramSettings(BaseModel):
    source_channels: list[str] = Field(default_factory=list)
    target_channel: str = ""


class FilterSettings(BaseModel):
    blacklist_region_categories: list[str] = Field(default_factory=list)
    blacklist_genres: list[str] = Field(default_factory=list)
    blacklist_genre_ids: list[int] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    telegram: TelegramSettings
    filters: FilterSettings


def read_config() -> tuple[dict[str, Any], dict[str, Any]]:
    raw: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        raw = yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}
    telegram = raw.get("telegram", {}) or {}
    filters = raw.get("filters", {}) or {}
    sources = [str(x) for x in telegram.get("source_channels", [])] or ["@" + wf.SOURCE]
    settings = {
        "telegram": {
            "source_channels": sources,
            "target_channel": str(telegram.get("target_channel") or wf.TARGET),
        },
        "filters": {
            "blacklist_region_categories": [
                str(x) for x in filters.get("blacklist_region_categories", [])
            ],
            "blacklist_genres": [str(x) for x in filters.get("blacklist_genres", [])],
            "blacklist_genre_ids": [int(x) for x in filters.get("blacklist_genre_ids", [])],
        },
    }
    return settings, raw


def write_config(payload: SettingsPayload) -> dict[str, Any]:
    _, raw = read_config()
    raw.setdefault("telegram", {})
    raw.setdefault("filters", {})
    raw["telegram"]["source_channels"] = [
        x.strip() for x in payload.telegram.source_channels if x.strip()
    ]
    raw["telegram"]["target_channel"] = payload.telegram.target_channel.strip()
    raw["filters"]["blacklist_region_categories"] = [
        x.strip() for x in payload.filters.blacklist_region_categories if x.strip()
    ]
    raw["filters"]["blacklist_genres"] = [
        x.strip() for x in payload.filters.blacklist_genres if x.strip()
    ]
    raw["filters"]["blacklist_genre_ids"] = [
        int(x) for x in payload.filters.blacklist_genre_ids
    ]
    CONFIG_PATH.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), "utf-8"
    )

    sources = raw["telegram"]["source_channels"]
    if sources:
        wf.SOURCE = str(sources[0]).lstrip("@")
    if raw["telegram"]["target_channel"]:
        wf.TARGET = str(raw["telegram"]["target_channel"])
    wf.reload_config(CONFIG_PATH)
    settings, _ = read_config()
    return settings


def db() -> sqlite3.Connection:
    con = sqlite3.connect(wf.DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def ensure_db() -> None:
    wf.init_db().close()


def stats_today() -> dict[str, int]:
    ensure_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    con = db()
    try:
        rows = con.execute(
            "SELECT decision, COUNT(*) AS n FROM records "
            "WHERE substr(created_at, 1, 10)=? GROUP BY decision",
            (today,),
        ).fetchall()
    finally:
        con.close()
    counts = {str(row["decision"]): int(row["n"]) for row in rows}
    return {
        "forwarded": counts.get("forwarded", 0),
        "filtered": counts.get("filtered", 0),
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0),
    }


def loop() -> None:
    con = wf.init_db()
    bot = wf.Bot(TOKEN)
    state["running"] = True
    try:
        while not stop_event.is_set():
            try:
                wf.run_once(
                    SimpleNamespace(
                        dry_run=False,
                        test_send=False,
                        backfill=None,
                        limit=0,
                        once=False,
                    ),
                    bot,
                    con,
                )
                state["last_error"] = ""
            except Exception as exc:
                state["last_error"] = str(exc)
                wf.log("loop error:", exc)
            state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            stop_event.wait(wf.POLL_SECONDS)
    finally:
        state["running"] = False
        con.close()


def start_loop() -> None:
    global loop_thread
    with loop_lock:
        if loop_thread and loop_thread.is_alive():
            return
        if not TOKEN:
            state["running"] = False
            state["last_error"] = "TELEGRAM_BOT_TOKEN missing"
            return
        stop_event.clear()
        loop_thread = threading.Thread(target=loop, daemon=True, name="bot-loop")
        loop_thread.start()
        state["running"] = True


def stop_loop() -> bool:
    global loop_thread
    with loop_lock:
        stop_event.set()
        if loop_thread and loop_thread.is_alive():
            loop_thread.join(timeout=90)
        if loop_thread and loop_thread.is_alive():
            state["last_error"] = "loop still stopping"
            return False
        loop_thread = None
        state["running"] = False
        return True


def test_forward() -> None:
    con = wf.init_db()
    try:
        bot = wf.Bot(TOKEN)
        wf.run_once(
            SimpleNamespace(
                dry_run=False,
                test_send=True,
                backfill=None,
                limit=0,
                once=True,
            ),
            bot,
            con,
        )
    finally:
        con.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_db()
    start_loop()
    yield
    stop_loop()


app = FastAPI(title="TG Bot Forwarder", lifespan=lifespan)


@app.get("/api/status")
def status() -> dict[str, Any]:
    settings, _ = read_config()
    sources = settings["telegram"]["source_channels"]
    return {
        "worker": {
            "running": bool(state["running"]),
            "can_start": bool(TOKEN),
            "session_exists": True,
            "last_error": state["last_error"],
            "last_run": state["last_run"],
        },
        "telegram": {
            "configured": bool(TOKEN),
            "source_count": len(sources),
            "target_channel": settings["telegram"]["target_channel"],
        },
        "tmdb": {"configured": bool(wf.TMDB_API_KEY), "language": "zh-CN"},
        "stats": stats_today(),
    }


@app.get("/api/records")
def records(limit: int = 100) -> dict[str, Any]:
    ensure_db()
    con = db()
    try:
        rows = con.execute(
            "SELECT id, mid, source_channel, title, tmdb_id, tmdb_media_type, "
            "tmdb_year, region_category, episode, decision, reason, created_at "
            "FROM records ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    finally:
        con.close()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "telegram_message_id": row["mid"],
                "source_channel": row["source_channel"],
                "title": row["title"],
                "tmdb_id": row["tmdb_id"],
                "tmdb_media_type": row["tmdb_media_type"],
                "tmdb_title": row["title"],
                "tmdb_year": row["tmdb_year"],
                "region_category": row["region_category"],
                "genres": [],
                "genre_ids": [],
                "decision": row["decision"],
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
        )
    return {"items": items}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    settings, _ = read_config()
    return settings


@app.put("/api/settings")
def put_settings(payload: SettingsPayload) -> dict[str, Any]:
    return write_config(payload)


@app.get("/api/telegram-login")
def telegram_login() -> dict[str, str]:
    return {"status": "bot", "message": "Bot 模式无需 Telegram 登录，使用 Bot Token 运行。"}


@app.post("/api/telegram-login/send-code")
def telegram_send_code() -> dict[str, str]:
    return {"status": "bot", "message": "Bot 模式无需发送验证码。"}


@app.post("/api/telegram-login/sign-in")
def telegram_sign_in() -> dict[str, str]:
    return {"status": "bot", "message": "Bot 模式无需登录。"}


@app.post("/api/worker/start")
def worker_start() -> dict[str, Any]:
    start_loop()
    return {"running": bool(state["running"]), "message": "Bot 监听已启动"}


@app.post("/api/worker/stop")
def worker_stop() -> dict[str, Any]:
    stop_loop()
    return {"running": False, "message": "Bot 监听已停止"}


@app.post("/api/worker/restart")
def worker_restart() -> dict[str, Any]:
    if not stop_loop():
        return {"running": bool(state["running"]), "message": "监听正在停止，请稍后再重启"}
    start_loop()
    return {"running": bool(state["running"]), "message": "Bot 监听已重启"}


@app.post("/api/worker/test-forward")
async def worker_test_forward() -> dict[str, Any]:
    try:
        await asyncio.to_thread(test_forward)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"running": bool(state["running"]), "message": "已触发一次测试转发"}


if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    target = DIST / path
    if path and target.exists() and target.is_file():
        return FileResponse(target)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "web/dist missing; run npm run build in web/"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.bot_api:app", host="0.0.0.0", port=8000)
