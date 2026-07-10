# TG TMDB Forwarder

Dockerized Telegram channel forwarder with TMDB classification, genre blacklist filtering, TMDB ids in forwarded messages, and a web dashboard.

## Features

- Uses a Telegram user account through Telethon.
- Listens to configured source channels.
- Extracts media title and year from Telegram message text.
- Searches TMDB and records `media_type/id`, titles, year, genres, and genre ids.
- Filters unwanted organizer-style categories such as `国产剧`, `欧美剧`, `国漫`, plus TMDB genres by name or id.
- Forwards approved posts to one target channel with TMDB metadata header.
- Serves a React dashboard at port `8000`.

## Configure

Copy examples:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env`:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_telegram_api_hash
TMDB_API_KEY=your_tmdb_api_key
```

Edit `config.yaml`:

```yaml
telegram:
  source_channels:
    - "@source_channel_username"
  target_channel: "@target_channel_username"

filters:
  blacklist_region_categories:
    - 国产剧
    - 欧美剧
  blacklist_genres:
    - Horror
  blacklist_genre_ids:
    - 99
```

## First Telegram Login

Run an interactive login once:

```bash
docker compose run --rm forwarder python -m app.login
```

Telethon stores the session in `./data/session`, so normal restarts do not need another login.

## Start

```bash
docker compose up -d --build
```

Dashboard:

```text
http://localhost:8000
```

Logs:

```bash
docker compose logs -f forwarder
```

## Forwarded Header

```text
#电影 #动作 #科幻
片名：沙丘2 / Dune: Part Two
年份：2024
TMDB：movie/693134
链接：https://www.themoviedb.org/movie/693134
```

## Notes

- The Telegram account must already be able to read the source channels and post to the target channel.
- If no Telegram/TMDB credentials are configured, the dashboard still starts and shows setup status.
- SQLite data and Telegram session files live under `./data`.
