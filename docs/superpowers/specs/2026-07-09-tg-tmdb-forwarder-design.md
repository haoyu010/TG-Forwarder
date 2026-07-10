# TG TMDB Forwarder Design

## Goal

Build a Dockerized Telegram channel forwarding service with a polished web dashboard. The service uses a Telegram user account to listen to source channels, reads each message title, searches TMDB, filters unwanted TMDB categories through a blacklist, and forwards approved posts to one target channel with classification tags and TMDB identifiers.

## Architecture

The system has one FastAPI application that owns the backend API, SQLite database, TMDB client, forwarding rules, and Telethon worker. A React/Vite dashboard is built into static assets and served by FastAPI in the production container. Docker Compose mounts persistent `data/` storage for the SQLite database and Telegram session.

The backend can run even before Telegram is logged in. The dashboard reports login state, worker state, TMDB status, recent decisions, and configuration. Configuration is loaded from `config.yaml` and environment variables, with dashboard endpoints for safe runtime edits that persist back to YAML.

## Telegram Flow

1. Telethon logs in as a Telegram user account using `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and a session file under `data/session/`.
2. The worker subscribes to configured source channel identifiers.
3. For each new message, it extracts the title from the first useful line.
4. The title parser removes common release noise and keeps an optional year.
5. The TMDB client uses `/search/multi` and genre lookup endpoints to resolve media metadata.
6. The rules engine filters blacklisted genre names or genre ids.
7. Approved messages are forwarded to the single configured target channel with a generated metadata header.
8. Every decision is stored in SQLite.

## Forwarded Message Header

Approved forwarded messages include a header before the original text:

```text
#电影 #动作 #科幻
片名：沙丘2 / Dune: Part Two
年份：2024
TMDB：movie/693134
链接：https://www.themoviedb.org/movie/693134
```

The TMDB line always includes both `media_type` and numeric TMDB id. The link uses `https://www.themoviedb.org/{media_type}/{id}`.

## Dashboard

The dashboard is an operational product UI, not a landing page. It uses a left sidebar, compact top status bar, cards only for metric summaries, and tables for records.

Sections:

- Overview: worker status, Telegram auth status, TMDB status, today forwarded, filtered, failed, and pending counts.
- Records: message title, source channel, TMDB id, media type, genres, action, reason, and timestamp.
- Channels: source channel list, target channel, enabled flag.
- Filters: blacklisted genre names and genre ids.
- Preview: paste a title and original text to see TMDB match, blacklist decision, and final header.
- Logs: recent structured events with severity and source.

Design system:

- Product register with restrained color strategy.
- Dense dashboard layout with clear table scanning.
- Primary color anchored around violet/indigo, status colors for success, warning, danger, and info.
- One practical sans font stack in the app; monospaced digits for TMDB ids and counters.
- All icon buttons use Lucide icons with accessible labels.
- No Codex browser preview is used for UI work; UI checks use MCP or command-line build/static checks.

## Data Model

`events` stores pipeline decisions:

- `id`
- `telegram_message_id`
- `source_channel`
- `title`
- `tmdb_id`
- `tmdb_media_type`
- `tmdb_title`
- `tmdb_year`
- `genres_json`
- `genre_ids_json`
- `decision`
- `reason`
- `created_at`

`settings` stores dashboard-editable JSON blobs for channel and filter settings.

## Error Handling

If title extraction fails, store a `failed` event with a reason and do not forward. If TMDB has no match, store `failed:no_tmdb_match`. If a genre blacklist matches, store `filtered:blacklisted_genre`. Telegram and TMDB API errors are retried only where safe; otherwise they are recorded and surfaced in the dashboard.

## Testing

Backend unit tests cover title extraction, metadata header rendering, blacklist filtering, config loading, SQLite repository behavior, and API responses. Frontend verification uses TypeScript build and lint/static checks. Docker verification builds the image and checks container command wiring.
