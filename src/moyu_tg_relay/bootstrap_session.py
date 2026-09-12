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
import tempfile
from dataclasses import asdict

from typing import Any, Iterable, Optional, Sequence

from telethon import TelegramClient
from telethon.sessions import StringSession


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDERS = {
    "OTP_RELAY_BEARER_TOKEN": {"generate-a-secure-random-token-here"},
    "TELEGRAM_API_ID": {"12345678", "0", ""},
    "TELEGRAM_API_HASH": {"0123456789abcdef0123456789abcdef", ""},
    "TELEGRAM_ACCOUNT_ID": {"123456789", ""},
}


def is_placeholder(key: str, val: Optional[str]) -> bool:
    v = str(val or "").strip()
    if not v:
        return True
    return v in _PLACEHOLDERS.get(key, set())


def load_env_file(path: str) -> dict[str, str]:
    """Read KEY=VALUE settings supporting single-line and multiline quoted strings."""
    values: dict[str, str] = {}
    env_path = Path(path).expanduser()
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SystemExit(f"Unable to read env file {env_path}: {error}") from error

    idx = 0
    length = len(text)
    line_number = 1

    while idx < length:
        while idx < length and text[idx] in (" ", "\t", "\r"):
            idx += 1
        if idx >= length:
            break
        if text[idx] == "\n":
            line_number += 1
            idx += 1
            continue
        if text[idx] == "#":
            while idx < length and text[idx] != "\n":
                idx += 1
            continue

        if text[idx:].startswith("export "):
            idx += 7
            while idx < length and text[idx] in (" ", "\t"):
                idx += 1

        eq_pos = text.find("=", idx)
        nl_pos = text.find("\n", idx)
        if eq_pos == -1 or (nl_pos != -1 and eq_pos > nl_pos):
            raise SystemExit(f"Invalid env file line {line_number}: expected KEY=VALUE")

        key = text[idx:eq_pos].strip()
        if not _ENV_KEY.fullmatch(key):
            raise SystemExit(f"Invalid env key on line {line_number}: {key!r}")

        idx = eq_pos + 1
        while idx < length and text[idx] in (" ", "\t"):
            idx += 1

        if idx >= length or text[idx] == "\n":
            values[key] = ""
            continue

        first_char = text[idx]
        if first_char in ("'", '"'):
            quote = first_char
            idx += 1
            val_start = idx
            while idx < length:
                if text[idx] == quote:
                    if quote == '"' and idx > val_start and text[idx - 1] == "\\":
                        idx += 1
                        continue
                    val = text[val_start:idx]
                    idx += 1
                    while idx < length and text[idx] != "\n":
                        idx += 1
                    line_number += val.count("\n")
                    values[key] = val
                    break
                elif text[idx] == "\n":
                    line_number += 1
                idx += 1
            else:
                raise SystemExit(f"Invalid env file line {line_number}: unclosed quote")
        else:
            end_line = text.find("\n", idx)
            if end_line == -1:
                val = text[idx:].strip()
                idx = length
            else:
                val = text[idx:end_line].strip()
                idx = end_line
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            values[key] = val

    return values


def update_env_content(
    text: str,
    updates: dict[str, str],
    remove_keys: Optional[Iterable[str]] = None,
) -> str:
    removals = set(remove_keys) if remove_keys else set()
    idx = 0
    length = len(text)
    entries: dict[str, tuple[int, int]] = {}

    while idx < length:
        line_start = idx
        while idx < length and text[idx] in (" ", "\t", "\r"):
            idx += 1
        if idx >= length:
            break
        if text[idx] == "\n":
            idx += 1
            continue
        if text[idx] == "#":
            while idx < length and text[idx] != "\n":
                idx += 1
            continue

        if text[idx:].startswith("export "):
            idx += 7
            while idx < length and text[idx] in (" ", "\t"):
                idx += 1

        eq_pos = text.find("=", idx)
        nl_pos = text.find("\n", idx)
        if eq_pos == -1 or (nl_pos != -1 and eq_pos > nl_pos):
            if nl_pos == -1:
                break
            idx = nl_pos + 1
            continue

        key = text[idx:eq_pos].strip()
        idx = eq_pos + 1
        while idx < length and text[idx] in (" ", "\t"):
            idx += 1

        if idx >= length or text[idx] == "\n":
            entries[key] = (line_start, idx)
            continue

        first_char = text[idx]
        if first_char in ("'", '"'):
            quote = first_char
            idx += 1
            while idx < length:
                if text[idx] == quote:
                    if quote == '"' and idx > 0 and text[idx - 1] == "\\":
                        idx += 1
                        continue
                    idx += 1
                    while idx < length and text[idx] != "\n":
                        idx += 1
                    break
                idx += 1
            entries[key] = (line_start, idx)
        else:
            end_line = text.find("\n", idx)
            if end_line == -1:
                idx = length
            else:
                idx = end_line
            entries[key] = (line_start, idx)

    sorted_entries = sorted(entries.items(), key=lambda item: item[1][0], reverse=True)
    res = text
    updated_keys = set()
    for key, (start, end) in sorted_entries:
        if key in removals and key not in updates:
            if end < len(res) and res[end] == "\n":
                end += 1
            res = res[:start] + res[end:]
        elif key in updates:
            val = updates[key]
            replacement = f"{key}={val}"
            res = res[:start] + replacement + res[end:]
            updated_keys.add(key)

    for key, val in updates.items():
        if key not in updated_keys:
            if res and not res.endswith("\n"):
                res += "\n"
            res += f"{key}={val}\n"

    return res


def update_env_file(
    env_path: Path,
    updates: dict[str, str],
    remove_keys: Optional[Iterable[str]] = None,
) -> None:
    """Safely update existing KEY=VALUE pairs or append new ones in an env file."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    content = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    new_content = update_env_content(content, updates, remove_keys=remove_keys)
    with tempfile.NamedTemporaryFile(mode="w", dir=env_path.parent, delete=False, encoding="utf-8") as handle:
        temporary = Path(handle.name)
        handle.write(new_content)
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(env_path)
    finally:
        temporary.unlink(missing_ok=True)


def load_account_rows_from_env(values: dict[str, str]) -> list[dict[str, Any]]:
    """Extract list of raw account dicts from parsed env values, supporting existing lists and placeholders."""
    raw_json = values.get("TELEGRAM_ACCOUNTS_JSON", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                result = []
                for item in parsed:
                    if isinstance(item, dict) and "account_id" in item:
                        cleaned: dict[str, Any] = {"account_id": str(item["account_id"]).strip()}
                        if "phone" in item and item["phone"]:
                            cleaned["phone"] = str(item["phone"]).strip()
                        if "username" in item and item["username"]:
                            cleaned["username"] = str(item["username"]).strip()
                        if "api_id" in item and item["api_id"]:
                            try:
                                cleaned["api_id"] = int(item["api_id"])
                            except (ValueError, TypeError):
                                pass
                        if "api_hash" in item and item["api_hash"]:
                            cleaned["api_hash"] = str(item["api_hash"]).strip()
                        if "session_string" in item and item["session_string"]:
                            cleaned["session_string"] = str(item["session_string"]).strip()
                        if "session_path" in item and item["session_path"]:
                            cleaned["session_path"] = str(item["session_path"]).strip()
                        result.append(cleaned)
                if result:
                    return result
        except Exception:
            pass

    # Fallback to legacy single account settings
    acc_id = values.get("TELEGRAM_ACCOUNT_ID", "").strip()
    sess_str = values.get("TELEGRAM_SESSION_STRING", "").strip()
    sess_path = values.get("TELEGRAM_SESSION_PATH", "").strip()
    if acc_id and (sess_str or sess_path):
        api_id_val = values.get("TELEGRAM_API_ID", "").strip()
        api_id = int(api_id_val) if api_id_val.isdigit() else 0
        api_hash = values.get("TELEGRAM_API_HASH", "").strip()
        entry: dict[str, Any] = {
            "account_id": acc_id,
            "api_id": api_id,
            "api_hash": api_hash,
        }
        if values.get("TELEGRAM_PHONE"):
            entry["phone"] = values["TELEGRAM_PHONE"].strip()
        if values.get("TELEGRAM_USERNAME"):
            entry["username"] = values["TELEGRAM_USERNAME"].strip()
        if sess_str:
            entry["session_string"] = sess_str
        elif sess_path:
            entry["session_path"] = sess_path
        return [entry]

    return []


def save_account_to_accounts_json(
    env_path: Path,
    *,
    account_id: str | int,
    api_id: int,
    api_hash: str,
    session_string: str = "",
    session_path: str = "",
    phone: str = "",
    username: str = "",
    bearer_token: str = "",
    remove_legacy: bool = True,
) -> list[dict[str, Any]]:
    """Merge or append an authorized account into TELEGRAM_ACCOUNTS_JSON with beautified formatting."""
    values = load_env_file(str(env_path)) if env_path.is_file() else {}
    existing_rows = load_account_rows_from_env(values)

    target_id = str(account_id).strip()
    matched = False
    for row in existing_rows:
        if str(row.get("account_id", "")).strip() == target_id:
            matched = True
            row["account_id"] = target_id
            row["api_id"] = api_id
            row["api_hash"] = api_hash
            if session_string:
                row["session_string"] = session_string
                row.pop("session_path", None)
            elif session_path:
                row["session_path"] = session_path
                row.pop("session_string", None)
            if phone:
                row["phone"] = phone
            if username:
                row["username"] = username
            break

    if not matched:
        new_row: dict[str, Any] = {
            "account_id": target_id,
        }
        if phone:
            new_row["phone"] = phone
        if username:
            new_row["username"] = username
        new_row["api_id"] = api_id
        new_row["api_hash"] = api_hash
        if session_string:
            new_row["session_string"] = session_string
        elif session_path:
            new_row["session_path"] = session_path
        existing_rows.append(new_row)

    formatted_json = json.dumps(existing_rows, ensure_ascii=False, indent=2)
    updates = {
        "TELEGRAM_ACCOUNTS_JSON": f"'{formatted_json}'",
    }
    if bearer_token:
        updates["OTP_RELAY_BEARER_TOKEN"] = bearer_token
    elif is_placeholder("OTP_RELAY_BEARER_TOKEN", values.get("OTP_RELAY_BEARER_TOKEN")):
        updates["OTP_RELAY_BEARER_TOKEN"] = secrets.token_hex(32)

    remove_keys = set()
    if remove_legacy:
        remove_keys.update({"TELEGRAM_ACCOUNT_ID", "TELEGRAM_SESSION_STRING"})

    update_env_file(env_path, updates, remove_keys=remove_keys)
    return existing_rows


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
    env_file_path: Optional[Path] = None,
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

    # 2. Telegram API ID & Hash discovery
    existing_accounts = load_account_rows_from_env(file_values)
    candidate = None
    for acc in existing_accounts:
        sess = acc.get("session_string", "")
        if not sess or sess.startswith("<") or is_placeholder("session_string", sess):
            candidate = acc
            break
    if candidate:
        print(f"  💡 检测到待就绪账号: UID {candidate.get('account_id')}")

    api_id_default = _setting(file_values, "TELEGRAM_API_ID").strip()
    if not api_id_default and candidate and candidate.get("api_id"):
        api_id_default = str(candidate["api_id"])

    api_id_str = api_id_default
    while is_placeholder("TELEGRAM_API_ID", api_id_str):
        print("\n  ℹ️ 未检测到有效 TELEGRAM_API_ID（可从 https://my.telegram.org 免费申请）")
        prompt = f"  请输入 Telegram API ID (纯数字){' [默认: ' + api_id_default + ']' if api_id_default else ''}: "
        raw_id = input(prompt).strip()
        if not raw_id and api_id_default and api_id_default.isdigit():
            api_id_str = api_id_default
            break
        if raw_id.isdigit():
            api_id_str = raw_id
            break
        print("  ⚠️ API ID 必须全部为数字，请重新输入。")
    api_id = int(api_id_str)

    api_hash_default = _setting(file_values, "TELEGRAM_API_HASH").strip()
    if not api_hash_default and candidate and candidate.get("api_hash"):
        api_hash_default = str(candidate["api_hash"])

    api_hash = api_hash_default
    while is_placeholder("TELEGRAM_API_HASH", api_hash):
        print("\n  ℹ️ 未检测到有效 TELEGRAM_API_HASH（32 位十六进制字符串）")
        prompt = f"  请输入 Telegram API Hash{' [默认: ' + api_hash_default + ']' if api_hash_default else ''}: "
        raw_hash = input(prompt).strip()
        if not raw_hash and api_hash_default and re.fullmatch(r"[0-9A-Fa-f]{32}", api_hash_default):
            api_hash = api_hash_default
            break
        if re.fullmatch(r"[0-9A-Fa-f]{32}", raw_hash):
            api_hash = raw_hash
            break
        print("  ⚠️ API Hash 必须为 32 位十六进制字符串，请检查后重新输入。")

    # Save preliminary credentials to .env
    update_env_file(
        target_env,
        {
            "OTP_RELAY_BEARER_TOKEN": token,
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

    # Write back to TELEGRAM_ACCOUNTS_JSON (multi-account environment variable)
    rows = save_account_to_accounts_json(
        target_env,
        account_id=account_id,
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        bearer_token=token,
    )
    print(f"  💾 凭据已自动写入多账号配置 TELEGRAM_ACCOUNTS_JSON: {target_env.name} (当前共 {len(rows)} 个账号)")

    print("\n" + "=" * 60)
    print("  🎉 Telegram 会话授权完成，凭据已全部就绪！")
    print("=" * 60)
    print(f"  Telegram Account ID : {account_id}")
    print(f"  Relay Bearer Token  : {token}")
    print(f"  Session String      : {session_string[:12]}...{session_string[-12:]}")
    print(f"  已自动写入配置文件  : {target_env.name} (多账号环境变量 TELEGRAM_ACCOUNTS_JSON)")
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
        "--add-account",
        action="store_true",
        help="Add a session to TELEGRAM_ACCOUNTS_JSON, preserving existing accounts",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run full guided wizard (auto-generates tokens, populates .env, syncs to vps-deploy)",
    )
    args = parser.parse_args()

    # If --file-session or explicit legacy session path is requested, maintain historical contract
    file_session = args.file_session or _explicit_session_path(sys.argv[1:])
    if args.add_account:
        target = Path(args.env_file) if args.env_file else Path(__file__).resolve().parents[2] / ".env"
        add_account(target, args.api_id, args.api_hash,
                    session_path=args.session_path if file_session else "")
        return
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


def add_account(env_path: Path, api_id: int, api_hash: str, *, session_path: str = "") -> None:
    """Authorize one additional account and atomically preserve the account list."""
    from .accounts import load_account_configs, normalize_session_path

    if not api_id or not api_hash:
        raise SystemExit("--add-account requires TELEGRAM_API_ID/API_HASH or --api-id/--api-hash")
    values = load_env_file(str(env_path)) if env_path.is_file() else {}
    # Read the destination file, so unrelated shell credentials cannot replace its accounts.
    existing = []
    if values.get("TELEGRAM_ACCOUNTS_JSON", "").strip() or values.get("TELEGRAM_ACCOUNT_ID", "").strip():
        try:
            existing = list(load_account_configs(values))
        except ValueError:
            raise SystemExit("Existing account configuration is invalid; no credentials were changed") from None
    if session_path and any(
        not item.session_string and item.normalized_session_path == normalize_session_path(session_path)
        for item in existing
    ):
        raise SystemExit("Use a different session path for the new account")
    if session_path:
        account_id = asyncio.run(bootstrap_file_session(api_id, api_hash, session_path))
        session_kwargs = {"session_path": str(Path(session_path).expanduser().resolve())}
    else:
        session_string, account_id = asyncio.run(bootstrap_string_session(api_id, api_hash))
        session_kwargs = {"session_string": session_string}
    if any(item.account_id == str(account_id) for item in existing):
        raise SystemExit("This account is already configured; existing credentials were preserved")
    rows = save_account_to_accounts_json(
        env_path,
        account_id=str(account_id),
        api_id=api_id,
        api_hash=api_hash,
        **session_kwargs,
    )
    print(f"Added Telegram account {account_id}; {len(rows)} accounts saved to {env_path}")


if __name__ == "__main__":
    main()
