"""One-time interactive bootstrap for Telegram Telethon sessions with auto-configuration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDERS = {
    "OTP_RELAY_BEARER_TOKEN": {"generate-a-secure-random-token-here"},
    "TELEGRAM_API_ID": {"12345678", "0", ""},
    "TELEGRAM_API_HASH": {"0123456789abcdef0123456789abcdef", ""},
    "TELEGRAM_ACCOUNT_ID": {"123456789", ""},
}


def is_placeholder(key: str, val: str | None) -> bool:
    v = str(val or "").strip()
    if not v:
        return True
    return v in _PLACEHOLDERS.get(key, set())


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


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Safely update existing KEY=VALUE pairs or append new ones in an env file."""
    if not env_path.is_file():
        lines = [f"{k}={v}\n" for k, v in updates.items()]
        env_path.write_text("".join(lines), encoding="utf-8")
        return

    content = env_path.read_text(encoding="utf-8")
    for key, value in updates.items():
        pattern = re.compile(rf"(?m)^[ \t]*(?:export[ \t]+)?{re.escape(key)}[ \t]*=.*$")
        if pattern.search(content):
            content = pattern.sub(f"{key}={value}", content)
        else:
            content = content.rstrip() + f"\n{key}={value}\n"
    env_path.write_text(content, encoding="utf-8")




def _setting(file_values: dict[str, str], name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    return file_values.get(name, default)


def _explicit_session_path(argv: list[str]) -> bool:
    return any(arg == "--session-path" or arg.startswith("--session-path=") for arg in argv)


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


def interactive_bootstrap(
    env_file_path: Path | None = None,
    *,
    force_token_regen: bool = False,
) -> int:
    """High-level guided bootstrap that generates tokens, configures .env, and syncs to vps-deploy."""
    root_dir = Path(__file__).resolve().parents[2]
    target_env = env_file_path or (root_dir / ".env")
    file_values = load_env_file(str(target_env)) if target_env.is_file() else {}

    print("\n" + "=" * 60)
    print("  🔑 Telegram 会话授权与 Relay 凭据自动化向导")
    print("=" * 60 + "\n")

    # 1. Bearer Token
    token = _setting(file_values, "OTP_RELAY_BEARER_TOKEN").strip()
    if force_token_regen or is_placeholder("OTP_RELAY_BEARER_TOKEN", token):
        token = secrets.token_hex(32)
        print(f"  ✨ 自动生成 256 位强随机 Relay Token: {token[:6]}***{token[-6:]}")
    else:
        print(f"  🔒 复用已有 Relay Bearer Token: {token[:6]}***{token[-6:]}")

    # 2. Telegram API ID
    api_id_str = _setting(file_values, "TELEGRAM_API_ID").strip()
    while is_placeholder("TELEGRAM_API_ID", api_id_str):
        print("\n  ℹ️ 未检测到有效 TELEGRAM_API_ID（可从 https://my.telegram.org 免费申请）")
        raw_id = input("  请输入 Telegram API ID (纯数字): ").strip()
        if raw_id.isdigit():
            api_id_str = raw_id
            break
        print("  ⚠️ API ID 必须全部为数字，请重新输入。")
    api_id = int(api_id_str)

    # 3. Telegram API Hash
    api_hash = _setting(file_values, "TELEGRAM_API_HASH").strip()
    while is_placeholder("TELEGRAM_API_HASH", api_hash):
        print("\n  ℹ️ 未检测到有效 TELEGRAM_API_HASH（32 位十六进制字符串）")
        raw_hash = input("  请输入 Telegram API Hash: ").strip()
        if re.fullmatch(r"[0-9A-Fa-f]{32}", raw_hash):
            api_hash = raw_hash
            break
        print("  ⚠️ API Hash 必须为 32 位十六进制字符串，请检查后重新输入。")

    # Save preliminary credentials to .env
    update_env_file(
        target_env,
        {
            "OTP_RELAY_BEARER_TOKEN": token,
            "TELEGRAM_API_ID": str(api_id),
            "TELEGRAM_API_HASH": api_hash,
        },
    )

    print("\n  📲 准备连接 Telegram MTProto 网关执行会话授权...")
    print("  💡 提示：将通过终端提示输入手机号 (如 +86...)、Telegram 验证码及 2FA 密码。\n")

    try:
        session_string, account_id = asyncio.run(
            bootstrap_string_session(api_id, api_hash)
        )
    except Exception as exc:
        print(f"\n  ❌ Telegram 授权失败: {exc}")
        return 1

    print(f"\n  ✅ 授权成功！Telegram Account ID: {account_id}")

    # Write back Account ID & StringSession to .env
    update_env_file(
        target_env,
        {
            "TELEGRAM_ACCOUNT_ID": str(account_id),
            "TELEGRAM_SESSION_STRING": session_string,
        },
    )
    print(f"  💾 凭据已自动写入本地: {target_env.name}")

    print("\n" + "=" * 60)
    print("  🎉 Telegram 会话授权完成，凭据已全部就绪！")
    print("=" * 60)
    print(f"  Telegram Account ID : {account_id}")
    print(f"  Relay Bearer Token  : {token}")
    print(f"  Session String      : {session_string[:12]}...{session_string[-12:]}")
    print(f"  已自动写入配置文件  : {target_env.name}")
    print("\n  💡 快速启动本地服务：")
    print("     python3 -m scripts.manager run")
    print("=" * 60 + "\n")
    return 0


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
    default_session_path = _setting(file_values, "TELEGRAM_SESSION_PATH").strip()
    if not default_session_path:
        if Path("./.state/telegram.session").is_file():
            default_session_path = "./.state/telegram.session"
        elif Path("./.state/hax-telegram.session").is_file():
            default_session_path = "./.state/hax-telegram.session"
        else:
            default_session_path = "./.state/telegram.session"

    parser.add_argument(
        "--session-path",
        default=default_session_path,
        help="Target file-session path; explicitly passing this implies --file-session",
    )
    parser.add_argument(
        "--file-session",
        action="store_true",
        help="Create a file-backed session instead of printing a StringSession",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run full guided wizard (auto-generates tokens, populates .env, syncs to vps-deploy)",
    )
    args = parser.parse_args()

    # If --file-session or explicit legacy session path is requested, maintain historical contract
    file_session = args.file_session or _explicit_session_path(sys.argv[1:])
    if file_session:
        if not args.api_id or not args.api_hash:
            raise SystemExit("TELEGRAM_API_ID and TELEGRAM_API_HASH are required for file session")
        asyncio.run(bootstrap_file_session(args.api_id, args.api_hash, args.session_path))
        return

    # If flags were explicitly passed non-interactively and completely:
    if args.api_id and args.api_hash and not args.interactive:
        session_string, account_id = asyncio.run(
            bootstrap_string_session(args.api_id, args.api_hash)
        )
        print(f"Telegram session authorised. TELEGRAM_ACCOUNT_ID={account_id}")
        print("Store the following value as a secret. Do not commit or log it:")
        print(f"TELEGRAM_SESSION_STRING={session_string}")
        return

    # Default to automated guided bootstrap
    env_path = Path(args.env_file) if args.env_file else None
    sys.exit(interactive_bootstrap(env_path))


if __name__ == "__main__":
    main()
