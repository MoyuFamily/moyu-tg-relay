"""FastAPI + Telethon interaction relay core.

Provider-specific Telegram message parsing and action policy live under
``moyu_tg_relay.providers``. The core owns transport, request lifecycle,
authentication, and applying provider decisions.
"""

from __future__ import annotations

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

from .admin_dashboard import render_admin_html
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
    workload_root = os.environ.get("MOYU_WORKLOAD_ROOT", "").strip()
    if workload_root:
        p = Path(workload_root) / ".state"
        p.mkdir(parents=True, exist_ok=True)
        return p
    if Path("/data").is_dir() and os.access("/data", os.W_OK):
        return Path("/data")
    if Path("/var/lib/moyu-tg-relay").is_dir() and os.access("/var/lib/moyu-tg-relay", os.W_OK):
        return Path("/var/lib/moyu-tg-relay")
    p = Path("./.state")
    p.mkdir(parents=True, exist_ok=True)
    return p


STATE_DIR = _resolve_state_dir()


def _resolve_session_path() -> str:
    explicit = os.environ.get("TELEGRAM_SESSION_PATH", "").strip()
    if explicit:
        return explicit
    for candidate in (
        STATE_DIR / "telegram.session",
        STATE_DIR / "hax-telegram.session",
        Path("./.state/telegram.session"),
        Path("./.state/hax-telegram.session"),
    ):
        if candidate.is_file():
            return str(candidate)
    return str(STATE_DIR / "telegram.session")


RELAY_TOKEN = os.environ.get("OTP_RELAY_BEARER_TOKEN", "").strip()
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
TELEGRAM_SESSION_PATH = _resolve_session_path()
TELEGRAM_ACCOUNT_ID = os.environ.get("TELEGRAM_ACCOUNT_ID", "").strip()
OTP_STORE_FILE = os.environ.get(
    "OTP_STORE_FILE",
    str(STATE_DIR / "pending_otp_store.json"),
).strip()
RELAY_LOG_DB_PATH = os.environ.get(
    "RELAY_LOG_DB_PATH",
    str(Path(OTP_STORE_FILE).parent / "relay_logs.db"),
).strip()
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "15") or 15)
store = PendingOtpStore(persistence_path=OTP_STORE_FILE)
log_store = RelayLogStore(db_path=RELAY_LOG_DB_PATH, retention_days=LOG_RETENTION_DAYS)
providers: dict[str, TelegramProvider] = build_provider_registry()
telegram: Optional[TelegramClient] = None
session_account_phone: str = ""
session_account_username: str = ""


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


def _validate_runtime() -> None:
    missing = []
    if not RELAY_TOKEN:
        missing.append("OTP_RELAY_BEARER_TOKEN")
    if not TELEGRAM_API_ID:
        missing.append("TELEGRAM_API_ID")
    if not TELEGRAM_API_HASH:
        missing.append("TELEGRAM_API_HASH")
    if not TELEGRAM_ACCOUNT_ID:
        missing.append("TELEGRAM_ACCOUNT_ID")
    if not TELEGRAM_SESSION_STRING and not TELEGRAM_SESSION_PATH:
        missing.append("TELEGRAM_SESSION_STRING or TELEGRAM_SESSION_PATH")
    if not providers:
        missing.append("at least one Telegram provider")
    if missing:
        raise RuntimeError("missing relay configuration: " + ", ".join(missing))


def _telegram_session():
    """Return the configured Telethon session backend."""
    if TELEGRAM_SESSION_STRING:
        try:
            return StringSession(TELEGRAM_SESSION_STRING)
        except Exception as error:
            raise RuntimeError("TELEGRAM_SESSION_STRING is invalid") from error
    return TELEGRAM_SESSION_PATH


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


def _prepare_telegram_session(use_ipv6: bool = False) -> Session:
    """Return an initialized Telethon Session instance with DC routing adapted."""
    raw = _telegram_session()
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


def _telegram_ready() -> bool:
    if telegram is None:
        return False
    try:
        return bool(telegram.is_connected())
    except Exception:
        return False


def _iter_message_buttons(msg_or_event: Any) -> tuple[Any, ...]:
    rows = getattr(msg_or_event, "buttons", None) or []
    return tuple(button for row in rows for button in (row or []))


def _provider_for(name: str) -> Optional[TelegramProvider]:
    return providers.get(str(name or "").strip().lower())


def _mark_human_required(detail: str, *, provider_name: str) -> None:
    request_id = store.mark_human_required(
        account=TELEGRAM_ACCOUNT_ID,
        detail=detail,
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
        account=TELEGRAM_ACCOUNT_ID,
        request_id=request_id or "",
        detail=detail,
    )


async def _process_incoming_telegram_message(
    *,
    sender_username: str,
    sender_id: str,
    text: str,
    buttons: tuple[Any, ...],
    request: PendingOtp,
) -> bool:
    provider = _provider_for(request.provider)
    if provider is None:
        _mark_human_required(
            f"provider is no longer available: {request.provider}",
            provider_name=request.provider,
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
            account=TELEGRAM_ACCOUNT_ID,
            request_id=request.request_id,
            detail="ignore",
            extra={"sender_username": sender_username, "sender_id": sender_id},
        )
        return False

    if decision.action == "code":
        request_id = store.attach_code(
            account=TELEGRAM_ACCOUNT_ID,
            code=decision.code,
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
            account=TELEGRAM_ACCOUNT_ID,
            request_id=request_id or request.request_id,
            detail="code attached",
            extra={"code_len": len(decision.code)},
        )
        return True

    if decision.action == "human_required":
        _mark_human_required(decision.detail, provider_name=provider.name)
        return True

    if decision.action != "click" or decision.button is None:
        _mark_human_required(
            f"provider returned unsupported action: {decision.action}",
            provider_name=provider.name,
        )
        return True

    btn_text = getattr(decision.button, "text", "")
    log_store.record(
        level="INFO",
        category="provider",
        message=f"准备自动点击 {provider.name} 确认按钮: {btn_text}",
        provider=provider.name,
        account=TELEGRAM_ACCOUNT_ID,
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
        )
        return True

    request_id = store.mark_auto_attempted(
        account=TELEGRAM_ACCOUNT_ID,
        detail=decision.detail,
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
        account=TELEGRAM_ACCOUNT_ID,
        request_id=request_id or request.request_id,
        detail=decision.detail,
    )
    return True


async def _handle_telegram_message(event: events.NewMessage.Event) -> None:
    request = store.active_request(TELEGRAM_ACCOUNT_ID)
    sender = await event.get_sender()
    sender_username = str(getattr(sender, "username", "") or "").lower()
    sender_id = str(getattr(sender, "id", "") or "")
    text = str(getattr(event, "raw_text", "") or "")
    buttons = _iter_message_buttons(event)
    btn_labels = [getattr(b, "text", "") for b in buttons if hasattr(b, "text")]

    # Record message in log store for full transparency
    log_store.record(
        level="INFO",
        category="telegram",
        message=f"收到来自 @{sender_username or sender_id} 的 Telegram 消息 (按钮数: {len(buttons)})",
        account=TELEGRAM_ACCOUNT_ID,
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
    )


async def _poll_pending_interaction(request: PendingOtp) -> None:
    if telegram is None:
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
            messages = await telegram.get_messages(target, limit=2)
            for msg in messages:
                if request.status != "pending":
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
                account=TELEGRAM_ACCOUNT_ID,
                request_id=request.request_id,
                detail=str(error),
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global telegram
    _validate_runtime()
    raw_session = _telegram_session()
    initial_session = SQLiteSession(str(raw_session)) if isinstance(raw_session, (str, Path)) else raw_session
    use_ipv6 = _detect_use_ipv6(session=initial_session if isinstance(initial_session, Session) else None)
    session = _prepare_telegram_session(use_ipv6=use_ipv6)
    telegram = TelegramClient(
        session,
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        use_ipv6=use_ipv6,
    )
    if use_ipv6 and telegram.session.dc_id in TELEGRAM_DC_IPV6_MAP:
        target_ip = TELEGRAM_DC_IPV6_MAP[telegram.session.dc_id]
        if telegram.session.server_address != target_ip:
            telegram.session.set_dc(
                telegram.session.dc_id, target_ip, telegram.session.port or 443
            )
    await telegram.connect()
    if not await telegram.is_user_authorized():
        await telegram.disconnect()
        telegram = None
        raise RuntimeError(
            "Telegram session is not authorised; run bootstrap_session.py first"
        )
    me = await telegram.get_me()
    if str(getattr(me, "id", "")) != TELEGRAM_ACCOUNT_ID:
        await telegram.disconnect()
        telegram = None
        raise RuntimeError(
            "TELEGRAM_ACCOUNT_ID does not match the authorised Telegram session"
        )
    global session_account_phone, session_account_username
    session_account_phone = str(getattr(me, "phone", "") or "").strip()
    session_account_username = str(getattr(me, "username", "") or "").strip().lower()
    telegram.add_event_handler(_handle_telegram_message, events.NewMessage(incoming=True))
    session_mode = "string" if TELEGRAM_SESSION_STRING else "file"
    provider_names = ",".join(sorted(providers))
    ip_mode = f"ipv6:dc{telegram.session.dc_id}" if use_ipv6 else f"ipv4:dc{telegram.session.dc_id}"
    print(
        f"[interaction-relay] Telegram session ready ({session_mode}, {ip_mode}); "
        f"providers={provider_names}"
    )
    # Prune expired logs on startup
    pruned_count = log_store.prune()
    log_store.record(
        level="INFO",
        category="system",
        message=f"Telegram 会话就绪 ({session_mode}, {ip_mode}); providers={provider_names}",
        account=TELEGRAM_ACCOUNT_ID,
        detail=f"startup_pruned={pruned_count}",
        extra={
            "session_mode": session_mode,
            "ip_mode": ip_mode,
            "providers": sorted(providers.keys()),
            "phone": session_account_phone,
            "username": session_account_username,
            "retention_days": LOG_RETENTION_DAYS,
        },
    )
    try:
        yield
    finally:
        log_store.record(
            level="INFO",
            category="system",
            message="Telegram Relay 服务正在关闭...",
            account=TELEGRAM_ACCOUNT_ID,
        )
        await telegram.disconnect()
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
    target = str(supplied or "").strip()
    if not target:
        return False
    if TELEGRAM_ACCOUNT_ID and target == TELEGRAM_ACCOUNT_ID:
        return True

    # 1. Phone number comparison (digits-only, supporting international/local formatting)
    phone_candidates: list[str] = []
    if session_account_phone:
        phone_candidates.append(session_account_phone)
    env_phone = os.environ.get("TELEGRAM_PHONE", "").strip()
    if env_phone:
        phone_candidates.append(env_phone)

    supplied_digits = "".join(c for c in target if c.isdigit())
    if supplied_digits:
        for p in phone_candidates:
            p_digits = "".join(c for c in str(p or "") if c.isdigit())
            if not p_digits:
                continue
            if supplied_digits == p_digits:
                return True
            if len(supplied_digits) >= 8 and len(p_digits) >= 8:
                if supplied_digits.endswith(p_digits) or p_digits.endswith(supplied_digits):
                    return True

    # 2. Username comparison (case-insensitive, optional @)
    user_candidates: list[str] = []
    if session_account_username:
        user_candidates.append(session_account_username)
    env_user = os.environ.get("TELEGRAM_USERNAME", "").strip().lower()
    if env_user:
        user_candidates.append(env_user)

    clean_supplied_user = target.lstrip("@").lower()
    if clean_supplied_user:
        for u in user_candidates:
            clean_u = str(u or "").strip().lstrip("@").lower()
            if clean_u and clean_supplied_user == clean_u:
                return True

    return False


@app.post(
    "/v1/otp/requests",
    response_model=CreateResponse,
    dependencies=[Depends(require_auth)],
)
def create_request(payload: CreateRequest) -> CreateResponse:
    provider_name = payload.provider.strip().lower()
    if _provider_for(provider_name) is None:
        raise HTTPException(status_code=400, detail="unsupported provider")
    if not _is_matching_account(payload.account):
        raise HTTPException(status_code=403, detail="account does not match relay session")
    account_key = TELEGRAM_ACCOUNT_ID or payload.account.strip()
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

    if request.status == "pending" and _telegram_ready():
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


@app.get("/api/admin/verify", dependencies=[Depends(require_auth)])
def admin_verify() -> dict[str, Any]:
    """Verify administrator Bearer authentication token."""
    return {
        "status": "ready" if _telegram_ready() else "not_ready",
        "account_id": TELEGRAM_ACCOUNT_ID,
        "phone": session_account_phone,
        "username": session_account_username,
    }


@app.get("/api/admin/stats", dependencies=[Depends(require_auth)])
def admin_stats() -> dict[str, Any]:
    """Aggregate overview metrics and runtime telemetry."""
    stats = log_store.get_stats()
    session_mode = "string" if TELEGRAM_SESSION_STRING else "file"
    dc_info = ""
    if telegram and getattr(telegram, "session", None):
        dc_info = f"DC {getattr(telegram.session, 'dc_id', '-')}"
        addr = getattr(telegram.session, "server_address", "")
        if addr:
            dc_info += f" ({addr})"
    stats["session_mode"] = session_mode
    stats["dc_info"] = dc_info
    stats["telegram"] = {
        "status": "ready" if _telegram_ready() else "not_ready",
        "account_id": TELEGRAM_ACCOUNT_ID,
        "phone": session_account_phone,
        "username": session_account_username,
    }
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


__all__ = ["app", "log_store", "providers", "store"]
