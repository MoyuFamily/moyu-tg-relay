"""FastAPI + Telethon service that relays Hax verification interactions.

The relay supports two Telegram session backends:

- ``TELEGRAM_SESSION_STRING`` for portable secret-backed deployments such as
  MOYUWORK1 workloads. This mode is preferred when present.
- ``TELEGRAM_SESSION_PATH`` for existing file-backed Docker/systemd deployments.

Besides one-time verification codes, the relay can recognize tightly-scoped Hax
Telegram confirmation cards. It attempts only explicitly allow-listed buttons
that Telethon can actually execute without opening a browser or requesting extra
user consent. Unknown, URL/UrlAuth, or failed interactions are surfaced as
``human_required`` so the caller can notify the user and keep the original
browser session alive for fallback.
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

from .store import PendingOtpStore, extract_hax_verification_code


RELAY_TOKEN = os.environ.get("OTP_RELAY_BEARER_TOKEN", "").strip()
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "").strip()
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
TELEGRAM_SESSION_PATH = os.environ.get(
    "TELEGRAM_SESSION_PATH", "./.state/hax-telegram.session"
).strip()
TELEGRAM_ACCOUNT_ID = os.environ.get("TELEGRAM_ACCOUNT_ID", "").strip()
HAX_TELEGRAM_BOT = os.environ.get("HAX_TELEGRAM_BOT", "HaxTG_bot").strip().lstrip("@")
HAX_AUTO_CONFIRM = os.environ.get("HAX_AUTO_CONFIRM", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _csv_values(name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())


HAX_CONFIRMATION_SENDER_IDS = frozenset(
    item for item in _csv_values("HAX_CONFIRMATION_SENDER_IDS", "777000") if item.isdigit()
)
HAX_CONFIRMATION_MARKERS = tuple(
    item.lower() for item in _csv_values("HAX_CONFIRMATION_MARKERS", "hax.co.id,hax")
)
HAX_AUTO_CONFIRM_BUTTONS = frozenset(
    item.lower()
    for item in _csv_values(
        "HAX_AUTO_CONFIRM_BUTTONS",
        "confirm,approve,authorize,accept,yes,continue",
    )
)
PROGRAMMATIC_BUTTON_TYPES = frozenset({"KeyboardButton", "KeyboardButtonCallback"})

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
    if missing:
        raise RuntimeError("missing relay configuration: " + ", ".join(missing))


def _telegram_session():
    """Return the configured Telethon session backend.

    Secret-backed StringSession takes precedence so workload deployments do not
    depend on a host-local session file. Existing file-backed deployments remain
    supported when TELEGRAM_SESSION_STRING is absent.
    """
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


def _normalized_button_text(button: Any) -> str:
    return " ".join(str(getattr(button, "text", "") or "").lower().split())


def _iter_message_buttons(event: events.NewMessage.Event) -> list[Any]:
    rows = getattr(event, "buttons", None) or []
    return [button for row in rows for button in (row or [])]


def _button_type_name(button: Any) -> str:
    """Return the underlying Telegram button type without relying on privates.

    Tests may provide a lightweight ``kind`` attribute. Real Telethon
    ``MessageButton`` objects expose the original TL object through ``button``.
    """
    explicit = str(getattr(button, "kind", "") or "").strip().lower()
    if explicit:
        return explicit
    original = getattr(button, "button", None)
    return type(original).__name__ if original is not None else "unknown"


def _is_programmatically_clickable(button: Any) -> bool:
    kind = _button_type_name(button)
    if kind in {"text", "callback"}:
        return True
    return kind in PROGRAMMATIC_BUTTON_TYPES


def _looks_like_hax_confirmation(
    *,
    sender_username: str,
    sender_id: str,
    text: str,
    buttons: list[Any],
) -> bool:
    if not buttons:
        return False

    request = store.active_request(TELEGRAM_ACCOUNT_ID)
    if request is None:
        return False

    source = request.context.get("source", "")
    stage = request.context.get("stage", "")
    if source and source != "renew-provider":
        return False
    if stage not in {"", "login", "renew"}:
        return False

    sender_allowed = (
        sender_username.lower() == HAX_TELEGRAM_BOT.lower()
        or sender_id in HAX_CONFIRMATION_SENDER_IDS
    )
    if not sender_allowed:
        return False
    normalized = " ".join(str(text or "").lower().split())
    return any(marker in normalized for marker in HAX_CONFIRMATION_MARKERS)


def _find_auto_confirm_button(buttons: list[Any]) -> Any | None:
    matches = [
        button
        for button in buttons
        if _normalized_button_text(button) in HAX_AUTO_CONFIRM_BUTTONS
    ]
    return matches[0] if len(matches) == 1 else None


def _mark_human_required(detail: str) -> None:
    request_id = store.mark_human_required(
        account=TELEGRAM_ACCOUNT_ID,
        detail=detail,
    )
    if request_id:
        print(f"[otp-relay] Hax confirmation requires human fallback for {request_id[:8]}…")


async def _handle_telegram_message(event: events.NewMessage.Event) -> None:
    sender = await event.get_sender()
    sender_username = str(getattr(sender, "username", "") or "").lower()
    sender_id = str(getattr(sender, "id", "") or "")
    text = str(getattr(event, "raw_text", "") or "")

    if sender_username == HAX_TELEGRAM_BOT.lower():
        code = extract_hax_verification_code(text)
        if code:
            request_id = store.attach_code(account=TELEGRAM_ACCOUNT_ID, code=code)
            if request_id:
                print(f"[otp-relay] Hax verification code attached to {request_id[:8]}…")
            return

    buttons = _iter_message_buttons(event)
    if not _looks_like_hax_confirmation(
        sender_username=sender_username,
        sender_id=sender_id,
        text=text,
        buttons=buttons,
    ):
        return

    button = _find_auto_confirm_button(buttons)
    if button is None:
        _mark_human_required(
            "检测到 Hax Telegram 确认卡片，但没有唯一的白名单确认按钮"
        )
        return

    if not HAX_AUTO_CONFIRM:
        _mark_human_required("检测到 Hax Telegram 确认卡片，但自动确认已关闭")
        return

    if not _is_programmatically_clickable(button):
        kind = _button_type_name(button)
        _mark_human_required(
            "检测到 Hax Telegram 确认卡片，但按钮类型 "
            f"{kind or 'unknown'} 不能由 Relay 安全自动执行"
        )
        return

    try:
        await button.click()
    except Exception as error:
        _mark_human_required(
            f"自动点击 Telegram 确认失败: {type(error).__name__}"
        )
        return

    request_id = store.mark_auto_attempted(
        account=TELEGRAM_ACCOUNT_ID,
        detail="已尝试自动点击 Telegram 确认，等待 Hax 页面继续",
    )
    if request_id:
        print(f"[otp-relay] automatic Hax confirmation attempted for {request_id[:8]}…")


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
    print(
        f"[otp-relay] Telegram session ready ({session_mode}); Hax bot=@{HAX_TELEGRAM_BOT}; "
        f"auto-confirm={'on' if HAX_AUTO_CONFIRM else 'off'}"
    )
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
    """Readiness probe: the relay is connected to Telegram and can receive interactions."""
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
    request = store.create(
        payload.account,
        payload.ttl_seconds,
        context=payload.context,
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


__all__ = ["app", "store"]
