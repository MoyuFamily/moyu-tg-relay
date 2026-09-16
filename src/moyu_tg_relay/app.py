"""FastAPI + Telethon interaction relay core.

Provider-specific Telegram message parsing and action policy live under
``moyu_tg_relay.providers``. The core owns transport, request lifecycle,
authentication, and applying provider decisions.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import secrets
import socket
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from telethon import TelegramClient, events
from telethon.sessions import SQLiteSession, StringSession
from telethon.sessions.abstract import Session

from .admin_dashboard import render_admin_html, TG_RELAY_LOGO_SVG
from .accounts import (
    AccountConfig,
    AccountIdentity,
    AccountRuntime,
    identity_from_config,
    identity_from_me,
    load_account_configs,
    make_runtime,
    normalize_phone,
    normalize_username,
)
from .log_store import RelayLogStore
from .providers import IncomingMessage, TelegramProvider, build_provider_registry
from .store import PendingOtpStore


TELEGRAM_DC_IPV6_MAP: dict[int, str] = {
    1: "2001:b28:f23d:f001::a",
    2: "2001:67c:4e8:f002::a",
    3: "2001:b28:f23d:f003::a",
    4: "2001:67c:4e8:f004::a",
    5: "2001:b28:f23f:f005::a",
}

TELEGRAM_DC_IPV4_MAP: dict[int, str] = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "149.154.171.5",
}


def _resolve_state_dir() -> Path:
    explicit_state = os.environ.get("STATE_DIR", "").strip()
    if explicit_state:
        p = Path(explicit_state)
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = Path("./.state")
    p.mkdir(parents=True, exist_ok=True)
    return p


STATE_DIR = _resolve_state_dir()


def _resolve_session_path(state_dir: Optional[Path] = None) -> str:
    base_state_dir = state_dir or _resolve_state_dir()
    explicit = os.environ.get("TELEGRAM_SESSION_PATH", "").strip()
    if explicit:
        p = Path(explicit)
        if not p.is_absolute() and (explicit.startswith("./.state") or explicit.startswith(".state")):
            return str(base_state_dir / p.name)
        return explicit
    for candidate in (
        base_state_dir / "telegram.session",
        base_state_dir / "hax-telegram.session",
        Path("./.state/telegram.session"),
        Path("./.state/hax-telegram.session"),
    ):
        if candidate.is_file():
            return str(candidate)
    return str(base_state_dir / "telegram.session")


RELAY_TOKEN = os.environ.get("OTP_RELAY_BEARER_TOKEN", "").strip()
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
TELEGRAM_SESSION_PATH = _resolve_session_path()
TELEGRAM_ACCOUNT_ID = os.environ.get("TELEGRAM_ACCOUNT_ID", "").strip()
TELEGRAM_ACCOUNTS_JSON = os.environ.get("TELEGRAM_ACCOUNTS_JSON", "")
OTP_STORE_FILE = os.environ.get(
    "OTP_STORE_FILE",
    str(STATE_DIR / "pending_otp_store.json"),
).strip()
RELAY_LOG_DB_PATH = os.environ.get(
    "RELAY_LOG_DB_PATH",
    str(Path(OTP_STORE_FILE).parent / "relay_logs.db"),
).strip()
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "15") or 15)
FILTER_CHAT_MESSAGES = os.environ.get("FILTER_CHAT_MESSAGES", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
SYSTEM_SENDER_IDS = frozenset({"777000", "42777"})
store = PendingOtpStore(persistence_path=OTP_STORE_FILE)
log_store = RelayLogStore(db_path=RELAY_LOG_DB_PATH, retention_days=LOG_RETENTION_DAYS)
providers: dict[str, TelegramProvider] = build_provider_registry()
telegram: Optional[TelegramClient] = None
session_account_phone: str = ""
session_account_username: str = ""
# ``account_runtimes`` is the multi-account registry.  ``accounts`` and
# ``runtimes`` are aliases kept for integrations/tests that used either name.
account_runtimes: dict[str, AccountRuntime] = {}
accounts = account_runtimes
runtimes = account_runtimes
_legacy_account_lock = asyncio.Lock()


class CreateRequest(BaseModel):
    provider: str
    account: str
    ttl_seconds: int = Field(default=300, ge=60, le=600)
    context: dict[str, Any] = Field(default_factory=dict)


class CreateResponse(BaseModel):
    request_id: str
    expires_in: int


class StatusResponse(BaseModel):
    request_id: str
    status: str
    detail: str = ""


class ConsumeResponse(BaseModel):
    code: str


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    expected = f"Bearer {RELAY_TOKEN}" if RELAY_TOKEN else ""
    supplied = str(authorization or "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _configured_account_configs() -> tuple[AccountConfig, ...]:
    """Read current settings, honoring an explicit multi-account JSON value."""
    env = dict(os.environ)
    # Globals remain patchable for the legacy unit tests and old integrations.
    raw_json = env.get("TELEGRAM_ACCOUNTS_JSON")
    if raw_json is None:
        raw_json = TELEGRAM_ACCOUNTS_JSON
    env["TELEGRAM_ACCOUNTS_JSON"] = raw_json
    for key, value in {
        "TELEGRAM_API_ID": str(TELEGRAM_API_ID),
        "TELEGRAM_API_HASH": TELEGRAM_API_HASH,
        "TELEGRAM_ACCOUNT_ID": TELEGRAM_ACCOUNT_ID,
        "TELEGRAM_SESSION_STRING": TELEGRAM_SESSION_STRING,
        "TELEGRAM_SESSION_PATH": TELEGRAM_SESSION_PATH,
    }.items():
        if key not in os.environ:
            env[key] = value
    return load_account_configs(env, legacy_session_path=TELEGRAM_SESSION_PATH)


def _validate_runtime() -> None:
    missing = []
    if not RELAY_TOKEN:
        missing.append("OTP_RELAY_BEARER_TOKEN")
    try:
        configs = _configured_account_configs()
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    if not providers:
        missing.append("at least one Telegram provider")
    for config in configs:
        if not config.api_id:
            missing.append(f"TELEGRAM_API_ID for account {config.account_id}")
        if not config.api_hash:
            missing.append(f"TELEGRAM_API_HASH for account {config.account_id}")
    if missing:
        raise RuntimeError("missing relay configuration: " + ", ".join(missing))


def _telegram_session(config: Optional[AccountConfig] = None):
    """Return a configured Telethon session backend (StringSession first)."""
    session_string = config.session_string if config else TELEGRAM_SESSION_STRING
    session_path = config.session_path if config else TELEGRAM_SESSION_PATH
    if session_string:
        try:
            return StringSession(session_string)
        except Exception as error:
            raise RuntimeError("TELEGRAM_SESSION_STRING is invalid") from error
    return session_path


def _probe_outbound_route(family: int, address: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if family == socket.AF_INET6:
                sock.connect((address, port, 0, 0))
            else:
                sock.connect((address, port))
            return True
    except OSError:
        return False


def _detect_has_ipv6() -> bool:
    """Check if the host has an active IPv6 outbound route."""
    for probe_addr in ("2001:67c:4e8:f002::a", "2606:4700:4700::1111"):
        if _probe_outbound_route(socket.AF_INET6, probe_addr, 443):
            return True
    return False


def _detect_has_ipv4() -> bool:
    """Check if the host has an active IPv4 outbound route."""
    for probe_addr in ("149.154.167.51", "1.1.1.1"):
        if _probe_outbound_route(socket.AF_INET, probe_addr, 443):
            return True
    return False


def _detect_use_ipv6(session: Optional[Session] = None) -> bool:
    """Determine whether to use IPv6 for Telegram connection."""
    raw_env = os.environ.get("TELEGRAM_USE_IPV6", "").strip().lower()
    if raw_env in ("1", "true", "yes", "on"):
        return True
    if raw_env in ("0", "false", "no", "off"):
        return False

    if session is not None and ":" in str(getattr(session, "server_address", "") or ""):
        return True

    has_v4 = _detect_has_ipv4()
    has_v6 = _detect_has_ipv6()
    # On IPv6-only environments (e.g. Hax VPS where IPv4 is unreachable), automatically use IPv6
    if not has_v4 and has_v6:
        return True
    return False


def _prepare_telegram_session(
    use_ipv6: bool = False,
    config: Optional[AccountConfig] = None,
    prepared_session: Optional[Session] = None,
) -> Session:
    """Return an initialized Telethon Session instance with DC routing adapted."""
    raw = prepared_session if prepared_session is not None else _telegram_session(config)
    if isinstance(raw, (str, Path)):
        session = SQLiteSession(str(raw))
    elif isinstance(raw, Session):
        session = raw
    else:
        raise TypeError(f"Unsupported session backend: {type(raw).__name__}")

    dc_id = getattr(session, "dc_id", 0) or 2
    port = getattr(session, "port", 0) or 443

    if use_ipv6:
        ipv6_ip = TELEGRAM_DC_IPV6_MAP.get(dc_id, TELEGRAM_DC_IPV6_MAP[2])
        session.set_dc(dc_id, ipv6_ip, port)
        print(f"[interaction-relay] Updated session to IPv6: DC {dc_id}, IP: {ipv6_ip}")
    else:
        server_addr = str(getattr(session, "server_address", "") or "")
        if ":" in server_addr:
            ipv4_ip = TELEGRAM_DC_IPV4_MAP.get(dc_id, TELEGRAM_DC_IPV4_MAP[2])
            session.set_dc(dc_id, ipv4_ip, port)
            print(f"[interaction-relay] Updated session to IPv4: DC {dc_id}, IP: {ipv4_ip}")

    return session


def _runtime_map() -> dict[str, AccountRuntime]:
    for candidate in (account_runtimes, accounts, runtimes):
        if candidate:
            return candidate
    return account_runtimes


def _client_ready(client: Any) -> bool:
    if client is None:
        return False
    try:
        return bool(client.is_connected())
    except Exception:
        return False


def _runtime_for(account_id: str) -> Optional[AccountRuntime]:
    return _runtime_map().get(str(account_id or "").strip())


def _telegram_ready(account_id: Optional[str] = None) -> bool:
    if account_id:
        runtime = _runtime_for(account_id)
        if runtime:
            return _client_ready(runtime.client)
        # With no multi-account registry the historical single client is the
        # only possible route; tests and old callers may create its store key
        # before setting TELEGRAM_ACCOUNT_ID.
        return _client_ready(telegram) if not _runtime_map() else False
    registry = _runtime_map()
    if registry:
        return all(_client_ready(runtime.client) for runtime in registry.values())
    return _client_ready(telegram)


def _iter_message_buttons(msg_or_event: Any) -> tuple[Any, ...]:
    rows = getattr(msg_or_event, "buttons", None) or []
    return tuple(button for row in rows for button in (row or []))


def _provider_for(name: str) -> Optional[TelegramProvider]:
    return providers.get(str(name or "").strip().lower())


def _account_lock(account_id: str) -> asyncio.Lock:
    runtime = _runtime_for(account_id)
    return runtime.lock if runtime else _legacy_account_lock


def _mark_human_required(
    detail: str,
    *,
    provider_name: str,
    account_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> str:
    account_key = str(account_id or TELEGRAM_ACCOUNT_ID).strip()
    request_id = store.mark_human_required(
        account=account_key,
        detail=detail,
        request_id=request_id,
    )
    if request_id:
        print(
            f"[interaction-relay] {provider_name} interaction requires human fallback "
            f"for {request_id[:8]}…"
        )
    log_store.record(
        level="WARNING",
        category="provider",
        message=f"{provider_name} 交互需要人工干预: {detail}",
        provider=provider_name,
        account=account_key,
        request_id=request_id or "",
        detail=detail,
    )
    return request_id


async def _process_incoming_telegram_message_unlocked(
    *,
    sender_username: str,
    sender_id: str,
    text: str,
    buttons: tuple[Any, ...],
    request: PendingOtp,
    account_id: Optional[str] = None,
) -> bool:
    account_key = str(account_id or request.account or TELEGRAM_ACCOUNT_ID).strip()
    provider = _provider_for(request.provider)
    if provider is None:
        _mark_human_required(
            f"provider is no longer available: {request.provider}",
            provider_name=request.provider,
            account_id=account_key,
            request_id=request.request_id,
        )
        return False

    message = IncomingMessage(
        sender_username=sender_username,
        sender_id=sender_id,
        text=text,
        buttons=buttons,
    )
    decision = provider.evaluate(message, request)

    if decision.action == "ignore":
        log_store.record(
            level="DEBUG",
            category="provider",
            message=f"{provider.name} 评估消息并忽略",
            provider=provider.name,
            account=account_key,
            request_id=request.request_id,
            detail="ignore",
            extra={"sender_username": sender_username, "sender_id": sender_id},
        )
        return False

    if decision.action == "code":
        request_id = store.attach_code(
            account=request.account,
            code=decision.code,
            request_id=request.request_id,
        )
        if request_id:
            print(
                f"[interaction-relay] {provider.name} code attached to "
                f"{request_id[:8]}…"
            )
        log_store.record(
            level="INFO",
            category="provider",
            message=f"捕获到 {provider.name} 验证码: {decision.code[:2]}***{decision.code[-2:] if len(decision.code) > 3 else ''}",
            provider=provider.name,
            account=request.account,
            request_id=request_id or request.request_id,
            detail="code attached",
            extra={"code_len": len(decision.code)},
        )
        return True

    if decision.action == "human_required":
        _mark_human_required(
            decision.detail,
            provider_name=provider.name,
            account_id=request.account,
            request_id=request.request_id,
        )
        return True

    if decision.action != "click" or decision.button is None:
        _mark_human_required(
            f"provider returned unsupported action: {decision.action}",
            provider_name=provider.name,
            account_id=account_key,
            request_id=request.request_id,
        )
        return True

    # Event delivery and active polling may evaluate the same card.  Only a
    # pending, current request can click; OTP updates remain valid after a
    # successful click or manual fallback.
    current = store.get(request.request_id)
    if current.account != account_key or current.status != "pending":
        return False

    btn_text = getattr(decision.button, "text", "")
    log_store.record(
        level="INFO",
        category="provider",
        message=f"准备自动点击 {provider.name} 确认按钮: {btn_text}",
        provider=provider.name,
        account=account_key,
        request_id=request.request_id,
        detail=decision.detail,
        extra={"button_text": btn_text},
    )

    try:
        await decision.button.click()
    except Exception as error:
        _mark_human_required(
            f"自动点击 Telegram 确认失败: {type(error).__name__}",
            provider_name=provider.name,
            account_id=account_key,
            request_id=request.request_id,
        )
        return True

    request_id = store.mark_auto_attempted(
        account=request.account,
        detail=decision.detail,
        request_id=request.request_id,
    )
    if request_id:
        print(
            f"[interaction-relay] automatic {provider.name} interaction attempted "
            f"for {request_id[:8]}…"
        )
    log_store.record(
        level="INFO",
        category="provider",
        message=f"已成功自动点击 {provider.name} 确认按钮: {btn_text}",
        provider=provider.name,
        account=request.account,
        request_id=request_id or request.request_id,
        detail=decision.detail,
    )
    return True


async def _process_incoming_telegram_message(
    *,
    sender_username: str,
    sender_id: str,
    text: str,
    buttons: tuple[Any, ...],
    request: PendingOtp,
    account_id: Optional[str] = None,
) -> bool:
    """Process one message under the account lock and request-id fence."""
    account_key = str(account_id or request.account or TELEGRAM_ACCOUNT_ID).strip()
    async with _account_lock(account_key):
        try:
            current = store.get(request.request_id)
        except KeyError:
            return False
        if current.account != account_key or current.status not in {
            "pending", "auto_attempted", "human_required"
        }:
            return False
        return await _process_incoming_telegram_message_unlocked(
            sender_username=sender_username,
            sender_id=sender_id,
            text=text,
            buttons=buttons,
            request=request,
            account_id=account_key,
        )


def _get_known_system_sender_ids() -> frozenset[str]:
    ids = set(SYSTEM_SENDER_IDS)
    for provider in providers.values():
        for sid in getattr(provider, "confirmation_sender_ids", ()):
            s = str(sid or "").strip()
            if s:
                ids.add(s)
    return frozenset(ids)


def _get_known_bot_usernames() -> frozenset[str]:
    bots = set()
    for provider in providers.values():
        b = str(getattr(provider, "bot_username", "") or "").strip().lower().lstrip("@")
        if b:
            bots.add(b)
    return frozenset(bots)


async def _is_bot_or_system_event(event: Any) -> bool:
    """Filter out regular chat messages (group chats, channels, 1-on-1 chats).

    Only allows messages from bots and Telegram system notifications.
    """
    if not FILTER_CHAT_MESSAGES:
        return True

    # 1. Early rejection for groups, supergroups, and broadcast channels
    if getattr(event, "is_group", False):
        return False
    if getattr(event, "is_channel", False):
        return False
    if getattr(event, "is_private", None) is False:
        return False

    system_ids = _get_known_system_sender_ids()

    # 2. Check event-level sender_id if available
    raw_sender_id = getattr(event, "sender_id", None)
    if raw_sender_id is not None and str(raw_sender_id).strip() in system_ids:
        return True

    # 3. Retrieve sender entity
    get_sender = getattr(event, "get_sender", None)
    if callable(get_sender):
        try:
            sender = await get_sender()
        except Exception:
            sender = None
    else:
        sender = getattr(event, "sender", None)

    if sender is None:
        return raw_sender_id is not None and str(raw_sender_id).strip() in system_ids

    # 4. Check sender ID against system IDs
    sid = str(getattr(sender, "id", "") or "").strip()
    if sid and sid in system_ids:
        return True

    # 5. Check if sender is a Bot
    if getattr(sender, "bot", False) is True:
        return True

    # 6. Check official support or verified status
    if getattr(sender, "support", False) is True or getattr(sender, "verified", False) is True:
        return True

    # 7. Check username suffix ('bot') or provider bot list
    username = str(getattr(sender, "username", "") or "").strip().lower().lstrip("@")
    if username:
        if username.endswith("bot") or username in _get_known_bot_usernames():
            return True

    # Otherwise, it's a regular user chat (单聊)
    return False


async def _handle_telegram_message(
    event: events.NewMessage.Event,
    account_id: Optional[str] = None,
) -> None:
    if FILTER_CHAT_MESSAGES and not await _is_bot_or_system_event(event):
        return

    if isinstance(account_id, AccountRuntime):
        account_id = account_id.account_id
    account_key = str(account_id or TELEGRAM_ACCOUNT_ID).strip()
    request = store.active_request(account_key)
    get_sender = getattr(event, "get_sender", None)
    if callable(get_sender):
        try:
            sender = await get_sender()
        except Exception:
            sender = None
    else:
        sender = getattr(event, "sender", None)
    sender_username = str(getattr(sender, "username", "") or "").lower()
    sender_id = str(getattr(sender, "id", "") or "")
    text = str(getattr(event, "raw_text", "") or "")
    buttons = _iter_message_buttons(event)
    btn_labels = [getattr(b, "text", "") for b in buttons if hasattr(b, "text")]

    # If no request is active under the exact Telegram account ID, attempt
    # resilient fallback matching when this sender uniquely matches one provider
    # with exactly one active request.
    if request is None:
        matched_provider = None
        for p in providers.values():
            p_bot = str(getattr(p, "bot_username", "") or "").strip().lower().lstrip("@")
            p_sids = set(str(s).strip() for s in getattr(p, "confirmation_sender_ids", ()))
            if (p_bot and sender_username == p_bot) or (sender_id and sender_id in p_sids):
                matched_provider = p.name
                break

        if matched_provider is not None:
            active_for_p = store.active_requests_for_provider(matched_provider)
            if len(active_for_p) == 1:
                request = active_for_p[0]

    # Record message in log store for full transparency
    log_store.record(
        level="INFO",
        category="telegram",
        message=f"收到来自 @{sender_username or sender_id} 的 Telegram 消息 (按钮数: {len(buttons)})",
        account=account_key,
        request_id=request.request_id if request else "",
        provider=request.provider if request else "",
        detail=f"buttons={len(buttons)}",
        extra={
            "sender_username": sender_username,
            "sender_id": sender_id,
            "buttons": btn_labels,
            "text_snippet": text[:300],
            "has_active_request": request is not None,
        },
    )

    if request is None:
        return

    await _process_incoming_telegram_message(
        sender_username=sender_username,
        sender_id=sender_id,
        text=text,
        buttons=buttons,
        request=request,
        account_id=request.account,
    )


async def _poll_pending_interaction(
    request: PendingOtp,
    client: Any = None,
) -> None:
    account_key = str(request.account or "").strip()
    runtime = _runtime_for(account_key)
    selected_client = runtime.client if runtime else (
        client if client is not None else (telegram if account_key == TELEGRAM_ACCOUNT_ID else None)
    )
    if not _client_ready(selected_client):
        return
    provider = _provider_for(request.provider)
    if provider is None:
        return

    targets: list[Any] = []
    if hasattr(provider, "confirmation_sender_ids"):
        for sid in getattr(provider, "confirmation_sender_ids"):
            targets.append(int(sid) if str(sid).isdigit() else sid)
    if hasattr(provider, "bot_username") and provider.bot_username:
        targets.append(provider.bot_username)

    for target in targets:
        try:
            messages = await selected_client.get_messages(target, limit=2)
            for msg in messages:
                try:
                    current = store.get(request.request_id)
                except KeyError:
                    return
                if current.account != account_key or current.status not in {"pending", "auto_attempted", "human_required"}:
                    return
                msg_date = getattr(msg, "date", None)
                if msg_date:
                    ts = msg_date.timestamp()
                    if ts < request.created_at - 10:
                        continue
                sender = await msg.get_sender()
                sender_username = str(getattr(sender, "username", "") or "").lower()
                sender_id = str(getattr(sender, "id", "") or "")
                text = str(getattr(msg, "raw_text", "") or "")
                buttons = _iter_message_buttons(msg)
                processed = await _process_incoming_telegram_message(
                    sender_username=sender_username,
                    sender_id=sender_id,
                    text=text,
                    buttons=buttons,
                    request=request,
                    account_id=account_key,
                )
                if processed:
                    return
        except Exception as error:
            print(f"[interaction-relay] active poll error for {target}: {error}")
            log_store.record(
                level="WARNING",
                category="telegram",
                message=f"主动轮询 {target} 异常: {error}",
                provider=request.provider,
                account=account_key,
                request_id=request.request_id,
                detail=str(error),
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global telegram, account_runtimes, accounts, runtimes, session_account_phone, session_account_username
    _validate_runtime()
    configs = _configured_account_configs()
    telegram = None
    session_account_phone = ""
    session_account_username = ""
    registry: dict[str, AccountRuntime] = {}
    account_runtimes = registry
    accounts = registry
    runtimes = registry
    provider_names = ",".join(sorted(providers))
    created: list[AccountRuntime] = []
    try:
        for config in configs:
            runtime = make_runtime(config)
            registry[config.account_id] = runtime
            created.append(runtime)
            raw_session = _telegram_session(config)
            initial_session = SQLiteSession(str(raw_session)) if isinstance(raw_session, (str, Path)) else raw_session
            use_ipv6 = _detect_use_ipv6(session=initial_session if isinstance(initial_session, Session) else None)
            try:
                session = _prepare_telegram_session(use_ipv6=use_ipv6, config=config, prepared_session=initial_session)
                client = TelegramClient(session, config.api_id, config.api_hash, use_ipv6=use_ipv6)
            except BaseException:
                initial_session.close()
                raise
            runtime.client = client
            if telegram is None:
                telegram = client
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorised; run bootstrap_session.py first")
            me = await client.get_me()
            if str(getattr(me, "id", "")) != config.account_id:
                raise RuntimeError("authorised Telegram session account ID does not match configuration")
            runtime.identity = identity_from_me(config, me)
            runtime.status = "ready"
            handler = (lambda bound_id: (lambda event: _handle_telegram_message(event, bound_id)))(config.account_id)
            client.add_event_handler(
                handler,
                events.NewMessage(incoming=True, func=_is_bot_or_system_event),
            )
            if config.account_id == TELEGRAM_ACCOUNT_ID or len(configs) == 1:
                session_account_phone = runtime.identity.phone
                session_account_username = runtime.identity.username
            ip_mode = f"ipv6:dc{client.session.dc_id}" if use_ipv6 else f"ipv4:dc{client.session.dc_id}"
            print(f"[interaction-relay] Telegram session ready ({config.session_mode}, {ip_mode}); providers={provider_names}")
    except BaseException:
        for runtime in created:
            try:
                if runtime.client is not None:
                    await runtime.client.disconnect()
            except Exception:
                pass
            runtime.status = "not_ready"
        account_runtimes.clear()
        telegram = None
        raise
    try:
        # Prune expired logs on startup.
        pruned_count = log_store.prune()
        log_store.record(
            level="INFO",
            category="system",
            message=f"Telegram 会话就绪 ({len(configs)} accounts); providers={provider_names}",
            account=configs[0].account_id if configs else TELEGRAM_ACCOUNT_ID,
            detail=f"startup_pruned={pruned_count}, filter_chat_messages={FILTER_CHAT_MESSAGES}",
            extra={
                "account_count": len(configs),
                "providers": sorted(providers.keys()),
                "retention_days": LOG_RETENTION_DAYS,
                "filter_chat_messages": FILTER_CHAT_MESSAGES,
            },
        )
    except BaseException:
        for runtime in created:
            try:
                if runtime.client is not None:
                    await runtime.client.disconnect()
            except Exception:
                pass
            runtime.status = "not_ready"
        account_runtimes.clear()
        telegram = None
        raise
    try:
        yield
    finally:
        try:
            log_store.record(
                level="INFO",
                category="system",
                message="Telegram Relay 服务正在关闭...",
                account=configs[0].account_id if configs else TELEGRAM_ACCOUNT_ID,
            )
        finally:
            for runtime in list(_runtime_map().values()):
                try:
                    if runtime.client is not None:
                        await runtime.client.disconnect()
                except Exception:
                    pass
                runtime.status = "not_ready"
            account_runtimes.clear()
            telegram = None


app = FastAPI(
    title="Moyu Telegram Interaction Relay",
    version="1",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe: the HTTP process is running."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """Readiness probe: the relay is connected to Telegram."""
    if not _telegram_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram relay not ready",
        )
    return {"status": "ready"}


def _is_matching_account(supplied: str) -> bool:
    return _resolve_account_id(supplied) is not None


def _candidate_identities() -> list[AccountIdentity]:
    registry = _runtime_map()
    if registry:
        result: list[AccountIdentity] = []
        for runtime in registry.values():
            result.append(runtime.identity or identity_from_config(runtime.config))
        return result
    try:
        configs = _configured_account_configs()
    except ValueError:
        if TELEGRAM_ACCOUNT_ID:
            return [
                AccountIdentity(
                    TELEGRAM_ACCOUNT_ID,
                    session_account_phone or os.environ.get("TELEGRAM_PHONE", ""),
                    session_account_username or os.environ.get("TELEGRAM_USERNAME", ""),
                )
            ]
        return []
    result = []
    for config in configs:
        if config.account_id == TELEGRAM_ACCOUNT_ID and session_account_phone:
            result.append(
                AccountIdentity(
                    config.account_id,
                    session_account_phone,
                    session_account_username,
                    config.phone,
                    config.username,
                )
            )
        else:
            result.append(identity_from_config(config))
    return result


def _resolve_account_id(supplied: str) -> Optional[str]:
    """Resolve one request account, returning ``None`` for unknown/ambiguous."""
    target = str(supplied or "").strip()
    if not target:
        return None
    identities = _candidate_identities()
    # Exact ID always wins over aliases.
    target_id = str(int(target)) if target.isdigit() else target
    exact = [item.account_id for item in identities if target_id == item.account_id]
    if exact:
        return exact[0] if len(set(exact)) == 1 else None

    phone_input = normalize_phone(target)
    if phone_input:
        matches: list[str] = []
        for item in identities:
            for phone in item.phone_aliases:
                candidate = normalize_phone(phone)
                if not candidate:
                    continue
                if phone_input == candidate or (
                    len(phone_input) >= 8
                    and len(candidate) >= 8
                    and (phone_input.endswith(candidate) or candidate.endswith(phone_input))
                ):
                    matches.append(item.account_id)
                    break
        unique = set(matches)
        if len(unique) == 1:
            return next(iter(unique))
        return None

    username = normalize_username(target)
    if username:
        matches = [
            item.account_id
            for item in identities
            if username in item.username_aliases
        ]
        unique = set(matches)
        if len(unique) == 1:
            return next(iter(unique))
    return None


def _account_match_candidates(supplied: str) -> list[str]:
    target = str(supplied or "").strip()
    identities = _candidate_identities()
    target_id = str(int(target)) if target.isdigit() else target
    exact = [item.account_id for item in identities if target_id == item.account_id]
    if exact:
        return sorted(set(exact))
    phone_input = normalize_phone(target)
    if phone_input:
        matches = []
        for item in identities:
            if any(
                phone_input == normalize_phone(phone)
                or (
                    len(phone_input) >= 8
                    and len(normalize_phone(phone)) >= 8
                    and (
                        phone_input.endswith(normalize_phone(phone))
                        or normalize_phone(phone).endswith(phone_input)
                    )
                )
                for phone in item.phone_aliases
                if normalize_phone(phone)
            ):
                matches.append(item.account_id)
        return sorted(set(matches))
    username = normalize_username(target)
    return sorted({item.account_id for item in identities if username in item.username_aliases})


@app.post(
    "/v1/otp/requests",
    response_model=CreateResponse,
    dependencies=[Depends(require_auth)],
)
def create_request(payload: CreateRequest) -> CreateResponse:
    provider_name = payload.provider.strip().lower()
    if _provider_for(provider_name) is None:
        raise HTTPException(status_code=400, detail="unsupported provider")
    candidates = _account_match_candidates(payload.account)
    account_key = _resolve_account_id(payload.account)
    # Preserve the old helper as an extension point for legacy callers/tests.
    if account_key is None and _is_matching_account(payload.account):
        account_key = TELEGRAM_ACCOUNT_ID or payload.account.strip()
    if len(candidates) > 1:
        raise HTTPException(status_code=409, detail="account is ambiguous")
    if account_key is None:
        raise HTTPException(status_code=403, detail="account does not match relay session")
    request = store.create(
        account_key,
        payload.ttl_seconds,
        context=payload.context,
        provider=provider_name,
    )
    log_store.record(
        level="INFO",
        category="otp_request",
        message=f"创建 OTP 交互请求: {provider_name} ({account_key})",
        provider=provider_name,
        account=account_key,
        request_id=request.request_id,
        detail=f"ttl={payload.ttl_seconds}s",
        extra={"context": payload.context, "expires_in": payload.ttl_seconds},
    )
    return CreateResponse(
        request_id=request.request_id,
        expires_in=max(0, int(request.expires_at - request.created_at)),
    )


@app.get(
    "/v1/otp/requests/{request_id}",
    response_model=StatusResponse,
    dependencies=[Depends(require_auth)],
)
async def request_status(request_id: str) -> StatusResponse:
    try:
        request = store.get(request_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="request not found") from error

    if request.status in {"pending", "auto_attempted", "human_required"} and _telegram_ready(request.account):
        await _poll_pending_interaction(request)

    return StatusResponse(
        request_id=request.request_id,
        status=request.status,
        detail=request.detail,
    )


@app.post(
    "/v1/otp/requests/{request_id}/consume",
    response_model=ConsumeResponse,
    dependencies=[Depends(require_auth)],
)
def consume_request(request_id: str) -> ConsumeResponse:
    try:
        code = store.consume(request_id)
        log_store.record(
            level="INFO",
            category="otp_request",
            message=f"消费验证码成功: {request_id[:12]}…",
            request_id=request_id,
            detail="code consumed",
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="request not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ConsumeResponse(code=code)


@app.delete(
    "/v1/otp/requests/{request_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_auth)],
)
def cancel_request(request_id: str) -> Response:
    try:
        store.cancel(request_id)
        log_store.record(
            level="INFO",
            category="otp_request",
            message=f"取消交互请求: {request_id[:12]}…",
            request_id=request_id,
            detail="cancelled by client",
        )
        return Response(status_code=204)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="request not found") from error


# --- Admin Dashboard & Observability Endpoints ---


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def admin_dashboard_ui() -> HTMLResponse:
    """Serve the modern web admin console."""
    return HTMLResponse(content=render_admin_html())


@app.get("/favicon.ico")
def favicon_endpoint() -> Response:
    """Serve the SVG favicon directly for browser requests."""
    return Response(
        content=TG_RELAY_LOGO_SVG.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/admin/verify", dependencies=[Depends(require_auth)])
def admin_verify() -> dict[str, Any]:
    """Verify administrator Bearer authentication token."""
    entries = _admin_account_entries()
    result = {
        "status": "ready" if _telegram_ready() else "not_ready",
        "account_id": entries[0]["account_id"] if entries else TELEGRAM_ACCOUNT_ID,
        "phone": entries[0]["phone"] if entries else session_account_phone,
        "username": entries[0]["username"] if entries else session_account_username,
    }
    result.update({"accounts": entries, "account_count": len(entries),
                   "ready_count": sum(item["status"] == "ready" for item in entries)})
    return result


def _admin_account_entries() -> list[dict[str, Any]]:
    registry = _runtime_map()
    if registry:
        runtimes_to_report = list(registry.values())
    else:
        try:
            configs = _configured_account_configs()
        except ValueError:
            configs = ()
        runtimes_to_report = [
            AccountRuntime(config=config, identity=identity_from_config(config))
            for config in configs
        ]
        if len(runtimes_to_report) == 1 and TELEGRAM_ACCOUNT_ID:
            runtimes_to_report[0].identity = AccountIdentity(
                TELEGRAM_ACCOUNT_ID, session_account_phone,
                session_account_username,
                runtimes_to_report[0].config.phone,
                runtimes_to_report[0].config.username,
            )
            runtimes_to_report[0].client = telegram
    entries: list[dict[str, Any]] = []
    for runtime in runtimes_to_report:
        identity = runtime.identity or identity_from_config(runtime.config)
        client = runtime.client
        dc_info = ""
        session = getattr(client, "session", None)
        if session is not None:
            dc_info = f"DC {getattr(session, 'dc_id', '-') }"
            addr = getattr(session, "server_address", "")
            if addr:
                dc_info += f" ({addr})"
        entries.append({
            "account_id": identity.account_id,
            "phone": identity.phone,
            "username": identity.username,
            "status": "ready" if _client_ready(client) else "not_ready",
            "session_mode": runtime.config.session_mode,
            "dc_info": dc_info,
        })
    return entries


@app.get("/api/admin/stats", dependencies=[Depends(require_auth)])
def admin_stats() -> dict[str, Any]:
    """Aggregate overview metrics and runtime telemetry."""
    stats = log_store.get_stats()
    entries = _admin_account_entries()
    first = entries[0] if entries else {}
    session_mode = first.get("session_mode", "string" if TELEGRAM_SESSION_STRING else "file")
    dc_info = first.get("dc_info", "")
    stats["session_mode"] = session_mode
    stats["dc_info"] = dc_info
    stats["telegram"] = {
        "status": "ready" if _telegram_ready() else "not_ready",
        "account_id": first.get("account_id", TELEGRAM_ACCOUNT_ID),
        "phone": first.get("phone", session_account_phone),
        "username": first.get("username", session_account_username),
    }
    stats["accounts"] = entries
    stats["account_count"] = len(entries)
    stats["ready_count"] = sum(item["status"] == "ready" for item in entries)
    return stats


@app.get("/api/admin/logs", dependencies=[Depends(require_auth)])
def admin_query_logs(
    page: int = 1,
    page_size: int = 50,
    level: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[float] = None,
    until: Optional[float] = None,
    provider: Optional[str] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """Query paginated logs with multi-condition filters."""
    return log_store.query_logs(
        page=page,
        page_size=page_size,
        level=level,
        category=category,
        search=search,
        since=since,
        until=until,
        provider=provider,
        request_id=request_id,
    )


class PrunePayload(BaseModel):
    days: Optional[int] = None


@app.post("/api/admin/logs/prune", dependencies=[Depends(require_auth)])
def admin_prune_logs(payload: Optional[PrunePayload] = None) -> dict[str, int]:
    """Prune logs older than configured or specified retention days."""
    days = payload.days if (payload and payload.days) else LOG_RETENTION_DAYS
    deleted = log_store.prune(retention_days=days)
    log_store.record(
        level="INFO",
        category="system",
        message=f"执行日志手动清理，已清除 {deleted} 条超过 {days} 天的历史记录",
        detail=f"deleted={deleted}, retention_days={days}",
    )
    return {"deleted": deleted}


__all__ = [
    "app",
    "account_runtimes",
    "accounts",
    "log_store",
    "providers",
    "runtimes",
    "store",
]
