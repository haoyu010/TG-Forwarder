from dataclasses import dataclass

import pytest

from app.config import FilterSettings
from app.models import Genre, TmdbMatch
from app.storage import EventRepository
from app.telegram_worker import MAX_MEDIA_CAPTION_CHARS, MessageEnvelope, PipelineWorker, clean_forward_body_html, split_media_caption


@dataclass
class FakeTmdb:
    match: TmdbMatch | None

    async def search(self, title: str, year: int | None = None) -> TmdbMatch | None:
        self.last_title = title
        self.last_year = year
        return self.match


class FakeLookupTmdb(FakeTmdb):
    def __init__(self, match: TmdbMatch | None):
        super().__init__(match)
        self.lookup_calls: list[tuple[int, str | None]] = []
        self.search_called = False

    async def lookup(self, tmdb_id: int, media_type: str | None = None) -> TmdbMatch | None:
        self.lookup_calls.append((tmdb_id, media_type))
        return self.match

    async def search(self, title: str, year: int | None = None) -> TmdbMatch | None:
        self.search_called = True
        return await super().search(title, year)


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str, object | None]] = []

    async def send_message(self, target: str, text: str, media: object | None = None) -> None:
        self.sent.append((target, text, media))


@pytest.mark.anyio
async def test_worker_forwards_allowed_message_and_records_event(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    tmdb = FakeTmdb(
        TmdbMatch(
            tmdb_id=693134,
            media_type="movie",
            title="沙丘2",
            original_title="Dune: Part Two",
            year=2024,
            genres=[Genre(id=28, name="Action")],
        )
    )
    sender = FakeSender()
    worker = PipelineWorker(
        tmdb_client=tmdb,
        sender=sender,
        repository=repo,
        filters=FilterSettings(),
        target_channel="@target",
    )

    media = object()
    await worker.process_message(MessageEnvelope(message_id=7, source_channel="@source", text="Dune.Part.Two.2024.2160p", media=media))

    events = await repo.list_events()
    assert tmdb.last_title == "Dune Part Two"
    assert sender.sent[0][0] == "@target"
    assert "TMDB：" in sender.sent[0][1]
    assert "movie/693134" in sender.sent[0][1]
    assert "Dune.Part.Two.2024.2160p" in sender.sent[0][1]
    assert sender.sent[0][2] is media
    assert events[0].decision == "forwarded"


@pytest.mark.anyio
async def test_worker_uses_html_text_when_forwarding(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    tmdb = FakeTmdb(
        TmdbMatch(
            tmdb_id=228085,
            media_type="tv",
            title="一路朝阳",
            original_title="一路朝阳",
            year=2023,
            genres=[Genre(id=18, name="Drama")],
            region_category="国产剧",
        )
    )
    sender = FakeSender()
    worker = PipelineWorker(tmdb, sender, repo, FilterSettings(), "@target")

    await worker.process_message(
        MessageEnvelope(
            message_id=11,
            source_channel="@source",
            text="一路朝阳 2023 直达链接",
            html_text='一路朝阳 2023 <a href="https://example.test/pan">直达链接</a>',
        )
    )

    assert '<a href="https://example.test/pan">直达链接</a>' in sender.sent[0][1]


@pytest.mark.anyio
async def test_worker_prefers_tmdb_id_lookup_when_message_contains_id(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    tmdb = FakeLookupTmdb(
        TmdbMatch(
            tmdb_id=239901,
            media_type="tv",
            title="云秀行",
            original_title="云秀行",
            year=2026,
            genres=[Genre(id=18, name="剧情")],
            region_category="国产剧",
        )
    )
    sender = FakeSender()
    worker = PipelineWorker(tmdb, sender, repo, FilterSettings(), "@target")

    await worker.process_message(
        MessageEnvelope(
            message_id=12,
            source_channel="@source",
            text="📺 电视剧：**云秀行 (2026) 更新至36集 4K**\n🍿 TMDB ID：239901",
        )
    )

    assert tmdb.lookup_calls == [(239901, "tv")]
    assert tmdb.search_called is False
    assert "云秀行" in sender.sent[0][1]


@pytest.mark.anyio
async def test_worker_filters_blacklisted_tmdb_genre_without_sending(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    tmdb = FakeTmdb(
        TmdbMatch(
            tmdb_id=1,
            media_type="movie",
            title="Scary",
            original_title="Scary",
            year=2024,
            genres=[Genre(id=27, name="Horror")],
        )
    )
    sender = FakeSender()
    worker = PipelineWorker(
        tmdb_client=tmdb,
        sender=sender,
        repository=repo,
        filters=FilterSettings(blacklist_genres=["Horror"]),
        target_channel="@target",
    )

    await worker.process_message(MessageEnvelope(message_id=8, source_channel="@source", text="Scary 2024"))

    events = await repo.list_events()
    assert sender.sent == []
    assert events[0].decision == "filtered"
    assert events[0].reason == "blacklisted_genre:Horror"


@pytest.mark.anyio
async def test_worker_filters_blacklisted_region_category_without_sending(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    tmdb = FakeTmdb(
        TmdbMatch(
            tmdb_id=1,
            media_type="tv",
            title="国产剧示例",
            original_title="国产剧示例",
            year=2024,
            genres=[Genre(id=18, name="Drama")],
            region_category="国产剧",
        )
    )
    sender = FakeSender()
    worker = PipelineWorker(
        tmdb_client=tmdb,
        sender=sender,
        repository=repo,
        filters=FilterSettings(blacklist_region_categories=["国产剧"]),
        target_channel="@target",
    )

    await worker.process_message(MessageEnvelope(message_id=10, source_channel="@source", text="国产剧示例 2024"))

    events = await repo.list_events()
    assert sender.sent == []
    assert events[0].decision == "filtered"
    assert events[0].reason == "blacklisted_region:国产剧"


@pytest.mark.anyio
async def test_worker_records_failed_when_tmdb_has_no_match(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    await repo.initialize()
    sender = FakeSender()
    worker = PipelineWorker(
        tmdb_client=FakeTmdb(None),
        sender=sender,
        repository=repo,
        filters=FilterSettings(),
        target_channel="@target",
    )

    await worker.process_message(MessageEnvelope(message_id=9, source_channel="@source", text="Unknown Release 2026"))

    events = await repo.list_events()
    assert sender.sent == []
    assert events[0].decision == "failed"
    assert events[0].reason == "no_tmdb_match"


def test_split_media_caption_keeps_short_text_together_and_splits_long_text():
    short = "短内容"
    assert split_media_caption(short) == (short, "")

    long = "头部链接 <a href=\"https://example.test\">TMDB</a>\n\n" + ("内容" * MAX_MEDIA_CAPTION_CHARS)
    caption, remainder = split_media_caption(long)

    assert len(caption) <= MAX_MEDIA_CAPTION_CHARS
    assert caption.endswith("</a>")
    assert remainder


def test_clean_forward_body_html_removes_ad_lines_and_keeps_resource_links():
    body = "\n".join(
        [
            '直达链接 ｜ <a href="https://115cdn.com/s/example">百花杀</a>',
            "🌍： 群主自用机场: 守候网络, 9折活动!",
            "🔥： 阿里云盘播放神器: VidHub",
        ]
    )

    cleaned = clean_forward_body_html(body)

    assert "115cdn.com" in cleaned
    assert "群主自用机场" not in cleaned
    assert "VidHub" not in cleaned
