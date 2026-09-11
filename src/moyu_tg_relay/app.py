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
from pydantic import BaseModel, Field
from telethon import TelegramClient, events
from telethon.sessions import SQLiteSession, StringSession
from telethon.sessions.abstract import Session

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


def _resolve_session_path() -> str:
    explicit = os.environ.get("TELEGRAM_SESSION_PATH", "").strip()
    if explicit:
        return explicit
    if Path("./.state/telegram.session").is_file():
        return "./.state/telegram.session"
    if Path("./.state/hax-telegram.session").is_file():
        return "./.state/hax-telegram.session"
    return "./.state/telegram.session"


RELAY_TOKEN = os.environ.get("OTP_RELAY_BEARER_TOKEN", "").strip()
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
TELEGRAM_SESSION_PATH = _resolve_session_path()
TELEGRAM_ACCOUNT_ID = os.environ.get("TELEGRAM_ACCOUNT_ID", "").strip()

store = PendingOtpStore()
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


def _iter_message_buttons(event: events.NewMessage.Event) -> tuple[Any, ...]:
    rows = getattr(event, "buttons", None) or []
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


async def _handle_telegram_message(event: events.NewMessage.Event) -> None:
    request = store.active_request(TELEGRAM_ACCOUNT_ID)
    if request is None:
        return

    provider = _provider_for(request.provider)
    if provider is None:
        _mark_human_required(
            f"provider is no longer available: {request.provider}",
            provider_name=request.provider,
        )
        return

    sender = await event.get_sender()
    message = IncomingMessage(
        sender_username=str(getattr(sender, "username", "") or "").lower(),
        sender_id=str(getattr(sender, "id", "") or ""),
        text=str(getattr(event, "raw_text", "") or ""),
        buttons=_iter_message_buttons(event),
    )
    decision = provider.evaluate(message, request)

    if decision.action == "ignore":
        return

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
        return

    if decision.action == "human_required":
        _mark_human_required(decision.detail, provider_name=provider.name)
        return

    if decision.action != "click" or decision.button is None:
        _mark_human_required(
            f"provider returned unsupported action: {decision.action}",
            provider_name=provider.name,
        )
        return

    try:
        await decision.button.click()
    except Exception as error:
        _mark_human_required(
            f"自动点击 Telegram 确认失败: {type(error).__name__}",
            provider_name=provider.name,
        )
        return

    request_id = store.mark_auto_attempted(
        account=TELEGRAM_ACCOUNT_ID,
        detail=decision.detail,
    )
    if request_id:
        print(
            f"[interaction-relay] automatic {provider.name} interaction attempted "
            f"for {request_id[:8]}…"
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
    try:
        yield
    finally:
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
    return CreateResponse(
        request_id=request.request_id,
        expires_in=max(0, int(request.expires_at - request.created_at)),
    )


@app.get(
    "/v1/otp/requests/{request_id}",
    response_model=StatusResponse,
    dependencies=[Depends(require_auth)],
)
def request_status(request_id: str) -> StatusResponse:
    try:
        request = store.get(request_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="request not found") from error
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
        return Response(status_code=204)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="request not found") from error


__all__ = ["app", "providers", "store"]
