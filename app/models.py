from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ExtractedTitle:
    name: str
    year: int | None = None
    tmdb_id: int | None = None
    media_type_hint: str | None = None


@dataclass(frozen=True)
class Genre:
    id: int
    name: str


@dataclass(frozen=True)
class TmdbMatch:
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    year: int | None
    genres: list[Genre]
    original_language: str | None = None
    origin_country: list[str] | None = None
    region_category: str | None = None


@dataclass(frozen=True)
class FilterDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class PipelineEvent:
    telegram_message_id: int | None
    source_channel: str
    title: str
    tmdb_match: TmdbMatch | None
    decision: str
    reason: str
    id: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class StoredEvent:
    id: int
    telegram_message_id: int | None
    source_channel: str
    title: str
    tmdb_id: int | None
    tmdb_media_type: str | None
    tmdb_title: str | None
    tmdb_year: int | None
    region_category: str | None
    genres_json: str
    genre_ids_json: str
    decision: str
    reason: str
    created_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
