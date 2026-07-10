from __future__ import annotations

import asyncio

from telethon import TelegramClient

from app.config import load_config


async def login() -> None:
    config = load_config()
    if not config.telegram.api_id or not config.telegram.api_hash:
        raise SystemExit("TELEGRAM_API_ID and TELEGRAM_API_HASH are required before login.")
    client = TelegramClient(config.telegram.session_path, config.telegram.api_id, config.telegram.api_hash)
    await client.start()
    me = await client.get_me()
    print(f"Telegram login OK: {getattr(me, 'username', None) or getattr(me, 'id', 'unknown')}")
    await client.disconnect()


def main() -> None:
    asyncio.run(login())


if __name__ == "__main__":
    main()
