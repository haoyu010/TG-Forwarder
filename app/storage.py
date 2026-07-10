from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.models import PipelineEvent, StoredEvent, utc_now


class EventRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_message_id INTEGER,
                    source_channel TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tmdb_id INTEGER,
                    tmdb_media_type TEXT,
                    tmdb_title TEXT,
                    tmdb_year INTEGER,
                    region_category TEXT,
                    genres_json TEXT NOT NULL DEFAULT '[]',
                    genre_ids_json TEXT NOT NULL DEFAULT '[]',
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
            if "region_category" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN region_category TEXT")
            conn.commit()

    async def record_event(self, event: PipelineEvent) -> PipelineEvent:
        created_at = event.created_at or utc_now()
        match = event.tmdb_match
        genres = [genre.name for genre in match.genres] if match else []
        genre_ids = [genre.id for genre in match.genres] if match else []
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    telegram_message_id, source_channel, title, tmdb_id, tmdb_media_type,
                    tmdb_title, tmdb_year, region_category, genres_json, genre_ids_json, decision, reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.telegram_message_id,
                    event.source_channel,
                    event.title,
                    match.tmdb_id if match else None,
                    match.media_type if match else None,
                    match.title if match else None,
                    match.year if match else None,
                    match.region_category if match else None,
                    json.dumps(genres, ensure_ascii=False),
                    json.dumps(genre_ids),
                    event.decision,
                    event.reason,
                    created_at.isoformat(),
                ),
            )
            conn.commit()
            return replace(event, id=int(cursor.lastrowid), created_at=created_at)

    async def list_events(self, limit: int = 100) -> list[StoredEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, telegram_message_id, source_channel, title, tmdb_id,
                       tmdb_media_type, tmdb_title, tmdb_year, region_category, genres_json,
                       genre_ids_json, decision, reason, created_at
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    async def has_event_for_message(self, source_channel: str, telegram_message_id: int | None) -> bool:
        if telegram_message_id is None:
            return False
        aliases = _source_aliases(source_channel)
        placeholders = ", ".join("?" for _ in aliases)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT 1
                FROM events
                WHERE telegram_message_id = ?
                  AND source_channel IN ({placeholders})
                LIMIT 1
                """,
                (telegram_message_id, *aliases),
            ).fetchone()
        return row is not None

    async def stats_today(self) -> dict[str, int]:
        today = datetime.now(UTC).date().isoformat()
        stats = {"forwarded": 0, "filtered": 0, "failed": 0, "pending": 0}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT decision, COUNT(*)
                FROM events
                WHERE substr(created_at, 1, 10) = ?
                GROUP BY decision
                """,
                (today,),
            ).fetchall()
        for decision, count in rows:
            stats[str(decision)] = int(count)
        return stats

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> StoredEvent:
        return StoredEvent(
            id=int(row["id"]),
            telegram_message_id=row["telegram_message_id"],
            source_channel=str(row["source_channel"]),
            title=str(row["title"]),
            tmdb_id=row["tmdb_id"],
            tmdb_media_type=row["tmdb_media_type"],
            tmdb_title=row["tmdb_title"],
            tmdb_year=row["tmdb_year"],
            region_category=row["region_category"],
            genres_json=str(row["genres_json"]),
            genre_ids_json=str(row["genre_ids_json"]),
            decision=str(row["decision"]),
            reason=str(row["reason"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )


def _source_aliases(source_channel: str) -> tuple[str, ...]:
    raw = source_channel.strip()
    if not raw:
        return ("",)
    if raw.startswith("@"):
        return (raw, raw[1:])
    return (raw, f"@{raw}")
