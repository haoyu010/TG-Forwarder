import json

import pytest

from app.config import load_config
from app.models import Genre, PipelineEvent, TmdbMatch
from app.storage import EventRepository


def test_load_config_reads_channels_filters_and_env(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
telegram:
  source_channels:
    - "@source_one"
    - -100123456
  target_channel: "@target"
filters:
  blacklist_region_categories:
    - 国产剧
  blacklist_genres:
    - Horror
  blacklist_genre_ids:
    - 99
dashboard:
  host: "0.0.0.0"
  port: 8080
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TMDB_API_KEY", "tmdb")

    config = load_config(config_file)

    assert config.telegram.api_id == 123
    assert config.telegram.api_hash == "hash"
    assert config.tmdb.api_key == "tmdb"
    assert config.telegram.source_channels == ["@source_one", "-100123456"]
    assert config.telegram.target_channel == "@target"
    assert config.filters.blacklist_region_categories == ["国产剧"]
    assert config.filters.blacklist_genres == ["Horror"]
    assert config.filters.blacklist_genre_ids == [99]
    assert config.dashboard.port == 8080


def test_load_config_treats_empty_env_values_as_unconfigured(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("telegram: {}\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_API_ID", "")
    monkeypatch.setenv("TELEGRAM_API_HASH", "")
    monkeypatch.setenv("TMDB_API_KEY", "")

    config = load_config(config_file)

    assert config.telegram.api_id == 0
    assert config.telegram.api_hash == ""
    assert config.tmdb.api_key == ""


@pytest.mark.anyio
async def test_event_repository_persists_and_lists_events(tmp_path):
    db_path = tmp_path / "events.sqlite3"
    repo = EventRepository(db_path)
    await repo.initialize()
    match = TmdbMatch(
        tmdb_id=693134,
        media_type="movie",
        title="沙丘2",
        original_title="Dune: Part Two",
        year=2024,
        genres=[Genre(id=28, name="Action")],
    )

    event = PipelineEvent(
        telegram_message_id=42,
        source_channel="@source",
        title="Dune Part Two 2024",
        tmdb_match=match,
        decision="forwarded",
        reason="allowed",
    )
    saved = await repo.record_event(event)
    events = await repo.list_events(limit=10)
    stats = await repo.stats_today()

    assert saved.id is not None
    assert len(events) == 1
    assert events[0].tmdb_id == 693134
    assert json.loads(events[0].genres_json) == ["Action"]
    assert await repo.has_event_for_message("@source", 42) is True
    assert await repo.has_event_for_message("source", 42) is True
    assert await repo.has_event_for_message("@source", 43) is False
    assert stats["forwarded"] == 1
    assert stats["filtered"] == 0
    assert stats["failed"] == 0
