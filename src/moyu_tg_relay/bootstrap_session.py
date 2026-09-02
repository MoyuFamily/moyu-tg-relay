"""One-time interactive bootstrap for Telegram Telethon sessions."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: str) -> dict[str, str]:
    """Read simple KEY=VALUE settings without shell evaluation or expansion."""
    values: dict[str, str] = {}
    env_path = Path(path).expanduser()
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SystemExit(f"Unable to read env file {env_path}: {error}") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SystemExit(f"Invalid env file line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not _ENV_KEY.fullmatch(key):
            raise SystemExit(f"Invalid env key on line {line_number}: {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _setting(file_values: dict[str, str], name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    return file_values.get(name, default)


async def bootstrap_string_session(api_id: int, api_hash: str) -> tuple[str, int]:
    """Authorize interactively and return a portable StringSession plus account id."""
    session = StringSession()
    client = TelegramClient(session, api_id, api_hash)
    await client.start()
    me = await client.get_me()
    session_string = client.session.save()
    account_id = int(me.id)
    await client.disconnect()
    return session_string, account_id


async def bootstrap_file_session(api_id: int, api_hash: str, session_path: str) -> int:
    """Authorize interactively and persist a traditional file-backed session."""
    path_obj = Path(session_path).expanduser().resolve()
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(str(path_obj), api_id, api_hash)
    await client.start()
    me = await client.get_me()
    account_id = int(me.id)
    await client.disconnect()
    print(f"Telegram session authorised. TELEGRAM_ACCOUNT_ID={account_id}")
    print(f"Session saved to {path_obj}")
    return account_id


def main() -> None:
    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--env-file", default="")
    env_args, _ = env_parser.parse_known_args()
    file_values = load_env_file(env_args.env_file) if env_args.env_file else {}

    parser = argparse.ArgumentParser(description="Bootstrap Telegram Telethon Session")
    parser.add_argument(
        "--env-file",
        default=env_args.env_file,
        help="Optional literal KEY=VALUE env file; values are not shell-evaluated",
    )
    parser.add_argument(
        "--api-id",
        type=int,
        default=int(_setting(file_values, "TELEGRAM_API_ID", "0") or 0),
        help="Telegram API ID",
    )
    parser.add_argument(
        "--api-hash",
        default=_setting(file_values, "TELEGRAM_API_HASH").strip(),
        help="Telegram API Hash",
    )
    parser.add_argument(
        "--session-path",
        default=_setting(
            file_values,
            "TELEGRAM_SESSION_PATH",
            "./.state/telegram.session",
        ).strip(),
        help="Target session file path when --file-session is used",
    )
    parser.add_argument(
        "--file-session",
        action="store_true",
        help="Create the legacy file-backed session instead of printing a StringSession",
    )
    args = parser.parse_args()

    if not args.api_id or not args.api_hash:
        raise SystemExit(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are required "
            "(via flags, env, or --env-file)"
        )

    if args.file_session:
        asyncio.run(bootstrap_file_session(args.api_id, args.api_hash, args.session_path))
        return

    session_string, account_id = asyncio.run(
        bootstrap_string_session(args.api_id, args.api_hash)
    )
    print(f"Telegram session authorised. TELEGRAM_ACCOUNT_ID={account_id}")
    print("Store the following value as a secret. Do not commit or log it:")
    print(f"TELEGRAM_SESSION_STRING={session_string}")


if __name__ == "__main__":
    main()
