"""One-time interactive bootstrap for the Telegram Telethon session."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from telethon import TelegramClient


async def async_main(api_id: int, api_hash: str, session_path: str) -> None:
    path_obj = Path(session_path).expanduser().resolve()
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(str(path_obj), api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print(f"Telegram session authorised. TELEGRAM_ACCOUNT_ID={me.id}")
    print(f"Session saved to {path_obj}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Telegram Telethon Session")
    parser.add_argument(
        "--api-id",
        type=int,
        default=int(os.environ.get("TELEGRAM_API_ID", "0") or 0),
        help="Telegram API ID",
    )
    parser.add_argument(
        "--api-hash",
        default=os.environ.get("TELEGRAM_API_HASH", "").strip(),
        help="Telegram API Hash",
    )
    parser.add_argument(
        "--session-path",
        default=os.environ.get("TELEGRAM_SESSION_PATH", "./.state/telegram.session").strip(),
        help="Target session file path",
    )
    args = parser.parse_args()

    if not args.api_id or not args.api_hash:
        raise SystemExit("TELEGRAM_API_ID and TELEGRAM_API_HASH are required (via flags or env)")

    asyncio.run(async_main(args.api_id, args.api_hash, args.session_path))


if __name__ == "__main__":
    main()
