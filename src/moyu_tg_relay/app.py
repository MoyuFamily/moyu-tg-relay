"""FastAPI + Telethon interaction relay core.

Provider-specific Telegram message parsing and action policy live under
``moyu_tg_relay.providers``. The core owns transport, request lifecycle,
authentication, and applying provider decisions.
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from pathlib import Path

from .providers import IncomingMessage, TelegramProvider, build_provider_registry
from .store import PendingOtpStore


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
telegram: TelegramClient | None = None


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


def require_auth(authorization: str | None = Header(default=None)) -> None:
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


def _provider_for(name: str) -> TelegramProvider | None:
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
    telegram = TelegramClient(
        _telegram_session(),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
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
    telegram.add_event_handler(_handle_telegram_message, events.NewMessage(incoming=True))
    session_mode = "string" if TELEGRAM_SESSION_STRING else "file"
    provider_names = ",".join(sorted(providers))
    print(
        f"[interaction-relay] Telegram session ready ({session_mode}); "
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


@app.post(
    "/v1/otp/requests",
    response_model=CreateResponse,
    dependencies=[Depends(require_auth)],
)
def create_request(payload: CreateRequest) -> CreateResponse:
    provider_name = payload.provider.strip().lower()
    if _provider_for(provider_name) is None:
        raise HTTPException(status_code=400, detail="unsupported provider")
    if payload.account.strip() != TELEGRAM_ACCOUNT_ID:
        raise HTTPException(status_code=403, detail="account does not match relay session")
    request = store.create(
        payload.account,
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
