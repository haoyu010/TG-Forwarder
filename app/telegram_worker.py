from __future__ import annotations

import asyncio
import html as stdlib_html
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import FilterSettings, TelegramConfig
from app.models import PipelineEvent
from app.rules import FilterConfig, build_forward_header, evaluate_blacklist, extract_title
from app.storage import EventRepository

MAX_MEDIA_CAPTION_CHARS = 950


@dataclass(frozen=True)
class MessageEnvelope:
    message_id: int | None
    source_channel: str
    text: str
    html_text: str | None = None
    media: Any | None = None


class TmdbSearcher(Protocol):
    async def search(self, title: str, year: int | None = None) -> Any:
        ...


class MessageSender(Protocol):
    async def send_message(self, target: str, text: str, media: Any | None = None) -> None:
        ...


class PipelineWorker:
    def __init__(
        self,
        tmdb_client: TmdbSearcher,
        sender: MessageSender,
        repository: EventRepository,
        filters: FilterSettings,
        target_channel: str,
    ):
        self.tmdb_client = tmdb_client
        self.sender = sender
        self.repository = repository
        self.filters = filters
        self.target_channel = target_channel

    async def process_message(self, message: MessageEnvelope) -> None:
        extracted = extract_title(message.text)
        if not extracted.name:
            await self.repository.record_event(
                PipelineEvent(
                    telegram_message_id=message.message_id,
                    source_channel=message.source_channel,
                    title="",
                    tmdb_match=None,
                    decision="failed",
                    reason="empty_title",
                )
            )
            return

        match = None
        lookup = getattr(self.tmdb_client, "lookup", None)
        if extracted.tmdb_id and lookup:
            match = await lookup(extracted.tmdb_id, extracted.media_type_hint)
        if not match:
            match = await self.tmdb_client.search(extracted.name, extracted.year)
        if not match:
            await self.repository.record_event(
                PipelineEvent(
                    telegram_message_id=message.message_id,
                    source_channel=message.source_channel,
                    title=extracted.name,
                    tmdb_match=None,
                    decision="failed",
                    reason="no_tmdb_match",
                )
            )
            return

        decision = evaluate_blacklist(
            match,
            FilterConfig(
                blacklist_genres=self.filters.blacklist_genres,
                blacklist_genre_ids=self.filters.blacklist_genre_ids,
                blacklist_region_categories=self.filters.blacklist_region_categories,
            ),
        )
        if not decision.allowed:
            await self.repository.record_event(
                PipelineEvent(
                    telegram_message_id=message.message_id,
                    source_channel=message.source_channel,
                    title=extracted.name,
                    tmdb_match=match,
                    decision="filtered",
                    reason=decision.reason,
                )
            )
            return

        body = clean_forward_body_html(message.html_text or stdlib_html.escape(message.text))
        text = build_forward_header_html(match) + "\n\n" + body
        await self.sender.send_message(self.target_channel, text, message.media)
        await self.repository.record_event(
            PipelineEvent(
                telegram_message_id=message.message_id,
                source_channel=message.source_channel,
                title=extracted.name,
                tmdb_match=match,
                decision="forwarded",
                reason="allowed",
            )
        )


class TelethonSender:
    def __init__(self, client: Any | None = None):
        self.client = client

    def set_client(self, client: Any) -> None:
        self.client = client

    async def send_message(self, target: str, text: str, media: Any | None = None) -> None:
        if self.client is None:
            raise RuntimeError("Telegram client is not connected")
        if media is not None:
            caption, remainder = split_media_caption(text)
            try:
                await self.client.send_file(target, media, caption=caption, parse_mode="html")
            except Exception:
                await self.client.send_message(target, text, link_preview=False, parse_mode="html")
                return
            if remainder:
                await self.client.send_message(target, remainder, link_preview=False, parse_mode="html")
            return
        await self.client.send_message(target, text, link_preview=False, parse_mode="html")


class TelethonForwarderService:
    def __init__(
        self,
        telegram: TelegramConfig,
        pipeline: PipelineWorker,
    ):
        self.telegram = telegram
        self.pipeline = pipeline
        self.client: Any | None = None
        self.running = False
        self.poll_task: asyncio.Task[None] | None = None
        self.catch_up_limit = 10
        self.poll_interval_seconds = 600

    def apply_runtime_settings(self, filters: FilterSettings, target_channel: str) -> None:
        self.pipeline.filters = filters
        self.pipeline.target_channel = target_channel

    async def start(self) -> None:
        if self.running:
            return
        from telethon import TelegramClient, events

        self.client = TelegramClient(self.telegram.session_path, self.telegram.api_id, self.telegram.api_hash)
        if isinstance(self.pipeline.sender, TelethonSender):
            self.pipeline.sender.set_client(self.client)

        @self.client.on(events.NewMessage(chats=self.telegram.source_channels))
        async def handler(event: Any) -> None:
            chat = await event.get_chat()
            username = getattr(chat, "username", None)
            source = f"@{username}" if username else str(getattr(chat, "id", "unknown"))
            await self.pipeline.process_message(
                MessageEnvelope(
                    message_id=getattr(event.message, "id", None),
                    source_channel=source,
                    text=event.raw_text or "",
                    html_text=message_to_html(event.message),
                    media=getattr(event.message, "media", None),
                )
            )

        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            self.client = None
            self.running = False
            raise RuntimeError("Telegram 尚未登录，请先在后台完成验证码登录")
        self.running = True
        await self.catch_up_recent_messages()
        self.poll_task = asyncio.create_task(self._poll_recent_loop())

    async def stop(self) -> None:
        if self.poll_task:
            self.poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.poll_task
            self.poll_task = None
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.running = False

    async def catch_up_recent_messages(self) -> int:
        if not self.client or not self.running:
            return 0
        processed = 0
        for source in self.telegram.source_channels:
            messages = await self.client.get_messages(source, limit=self.catch_up_limit)
            for message in reversed(messages):
                message_id = getattr(message, "id", None)
                if await self.pipeline.repository.has_event_for_message(str(source), message_id):
                    continue
                text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
                await self.pipeline.process_message(
                    MessageEnvelope(
                        message_id=message_id,
                        source_channel=str(source),
                        text=text,
                        html_text=message_to_html(message),
                        media=getattr(message, "media", None),
                    )
                )
                processed += 1
        return processed

    async def _poll_recent_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self.poll_interval_seconds)
            with suppress(Exception):
                await self.catch_up_recent_messages()

    async def process_latest_message(self) -> str:
        if not self.client or not self.running:
            raise RuntimeError("监听服务未运行，请先启动监听")
        if not self.telegram.source_channels:
            raise RuntimeError("未配置源频道")

        source = self.telegram.source_channels[0]
        messages = await self.client.get_messages(source, limit=1)
        if not messages:
            raise RuntimeError("源频道没有可读取的消息")
        message = messages[0]
        text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
        await self.pipeline.process_message(
            MessageEnvelope(
                message_id=getattr(message, "id", None),
                source_channel=str(source),
                text=text,
                html_text=message_to_html(message),
                media=getattr(message, "media", None),
            )
        )
        return f"已处理源频道最新消息：{source}"


def build_forward_header_html(match: Any) -> str:
    original = match.original_title or match.title
    title_line = match.title if original == match.title else f"{match.title} / {original}"
    year = str(match.year) if match.year else "未知"
    tmdb_path = f"{match.media_type}/{match.tmdb_id}"
    link = f"https://www.themoviedb.org/{tmdb_path}"
    return "\n".join(
        [
            f"片名：{stdlib_html.escape(title_line)}",
            f"年份：{stdlib_html.escape(year)}",
            f'TMDB：<a href="{stdlib_html.escape(link)}">{stdlib_html.escape(tmdb_path)}</a>',
            f"分类：{stdlib_html.escape(match.region_category or '未分类')}",
            f'链接：<a href="{stdlib_html.escape(link)}">{stdlib_html.escape(link)}</a>',
        ]
    )


def message_to_html(message: Any) -> str:
    text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
    entities = getattr(message, "entities", None)
    if not entities:
        return stdlib_html.escape(text)
    try:
        from telethon.extensions import html as telethon_html

        return telethon_html.unparse(text, entities)
    except Exception:
        return stdlib_html.escape(text)


def clean_forward_body_html(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        plain = re.sub(r"<[^>]+>", "", raw_line).strip()
        if _is_ad_line(plain):
            continue
        cleaned_lines.append(raw_line)
    return "\n".join(cleaned_lines).strip()


def _is_ad_line(line: str) -> bool:
    if not line:
        return False
    return bool(
        line.startswith(("🌍", "🔥"))
        or "群主自用机场" in line
        or "守候网络" in line
        or "阿里云盘播放神器" in line
        or "VidHub" in line
        or "9折活动" in line
    )


def split_media_caption(text: str) -> tuple[str, str]:
    if len(text) <= MAX_MEDIA_CAPTION_CHARS:
        return text, ""

    cutoff = text.rfind("\n\n", 0, MAX_MEDIA_CAPTION_CHARS)
    if cutoff > 0:
        caption = text[:cutoff].rstrip()
        remainder = text[cutoff:].lstrip()
        return caption, remainder

    cutoff = text.rfind("\n", 0, MAX_MEDIA_CAPTION_CHARS)
    if cutoff < 200:
        cutoff = MAX_MEDIA_CAPTION_CHARS
    caption = text[:cutoff].rstrip()
    remainder = text[cutoff:].lstrip()
    return caption, remainder
