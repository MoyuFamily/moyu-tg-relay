"""One-time interactive bootstrap for the Hax relay Telethon session."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from telethon import TelegramClient


async def main() -> None:
    api_id = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session_path = os.environ.get(
        "TELEGRAM_SESSION_PATH", "./.state/hax-telegram.session"
    ).strip()
    if not api_id or not api_hash:
        raise SystemExit("TELEGRAM_API_ID / TELEGRAM_API_HASH are required")

    Path(session_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(session_path, api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print(f"Telegram session authorised. TELEGRAM_ACCOUNT_ID={me.id}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
