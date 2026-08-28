"""FastAPI + Telethon service that relays Hax verification codes.

Run this service on an independent private VPS. The Telethon session remains on
that VPS and is never passed to GitHub Actions or committed to this repository.
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from telethon import TelegramClient, events

from .store import PendingOtpStore, extract_hax_verification_code


RELAY_TOKEN = os.environ.get("OTP_RELAY_BEARER_TOKEN", "").strip()
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_PATH = os.environ.get(
    "TELEGRAM_SESSION_PATH", "./.state/hax-telegram.session"
).strip()
TELEGRAM_ACCOUNT_ID = os.environ.get("TELEGRAM_ACCOUNT_ID", "").strip()
HAX_TELEGRAM_BOT = os.environ.get("HAX_TELEGRAM_BOT", "HaxTG_bot").strip().lstrip("@")

store = PendingOtpStore()
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
    if missing:
        raise RuntimeError("missing relay configuration: " + ", ".join(missing))


def _telegram_ready() -> bool:
    if telegram is None:
        return False
    try:
        return bool(telegram.is_connected())
    except Exception:
        return False


async def _handle_telegram_message(event: events.NewMessage.Event) -> None:
    sender = await event.get_sender()
    sender_username = str(getattr(sender, "username", "") or "").lower()
    if sender_username != HAX_TELEGRAM_BOT.lower():
        return
    code = extract_hax_verification_code(event.raw_text)
    if not code:
        return
    request_id = store.attach_code(account=TELEGRAM_ACCOUNT_ID, code=code)
    if request_id:
        print(f"[otp-relay] Hax verification code attached to {request_id[:8]}…")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global telegram
    _validate_runtime()
    telegram = TelegramClient(
        TELEGRAM_SESSION_PATH,
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
    print(f"[otp-relay] Telegram session ready; Hax bot=@{HAX_TELEGRAM_BOT}")
    try:
        yield
    finally:
        await telegram.disconnect()
        telegram = None


app = FastAPI(
    title="Moyu Telegram OTP Relay",
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
    """Readiness probe: the relay is connected to Telegram and can receive OTPs."""
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
    if payload.provider.strip().lower() != "hax":
        raise HTTPException(status_code=400, detail="provider must be hax")
    if payload.account.strip() != TELEGRAM_ACCOUNT_ID:
        raise HTTPException(status_code=403, detail="account does not match relay session")
    request = store.create(payload.account, payload.ttl_seconds)
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
    return StatusResponse(request_id=request.request_id, status=request.status)


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


__all__ = ["app", "store"]
