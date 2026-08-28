"""In-memory short-lived interaction store for the Hax Telegram relay."""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass


CODE_PATTERN = re.compile(r"(?<!\d)(\d{6,10})(?!\d)")
CODE_HINTS = ("verification", "verify", "code", "renew")
ACTIVE_STATUSES = frozenset({"pending", "auto_attempted", "human_required", "ready"})
TERMINAL_STATUSES = frozenset({"consumed", "expired", "cancelled"})
TERMINAL_RETENTION_SECONDS = 600


@dataclass
class PendingOtp:
    request_id: str
    account: str
    created_at: float
    expires_at: float
    status: str = "pending"
    code: str = ""
    detail: str = ""


def extract_hax_verification_code(text: str) -> str:
    """Extract one plausible Hax verification code from a Telegram message.

    This deliberately fails closed when the message is unrelated or contains
    multiple numeric candidates. Confirmation cards are handled separately and
    never interpreted as OTP text.
    """
    normalized = " ".join(str(text or "").split())
    lower = normalized.lower()
    if not normalized or not any(hint in lower for hint in CODE_HINTS):
        return ""
    candidates = list(dict.fromkeys(CODE_PATTERN.findall(normalized)))
    return candidates[0] if len(candidates) == 1 else ""


class PendingOtpStore:
    """Thread-safe TTL store with one active interaction per Telegram account."""

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._items: dict[str, PendingOtp] = {}

    def _expire_locked(self) -> None:
        now = self._clock()
        stale_request_ids: list[str] = []
        for request_id, item in self._items.items():
            if item.status in ACTIVE_STATUSES and now >= item.expires_at:
                item.status = "expired"
                item.code = ""
                item.detail = ""
            if (
                item.status in TERMINAL_STATUSES
                and now >= item.expires_at + TERMINAL_RETENTION_SECONDS
            ):
                stale_request_ids.append(request_id)
        for request_id in stale_request_ids:
            del self._items[request_id]

    def create(self, account: str, ttl_seconds: int = 300) -> PendingOtp:
        normalized_account = str(account or "").strip()
        if not normalized_account:
            raise ValueError("account is required")
        ttl = max(60, min(int(ttl_seconds), 600))
        with self._lock:
            self._expire_locked()
            # A Telegram account can only have one current Hax interaction.
            # Cancelling the previous one removes message/button ambiguity.
            for item in self._items.values():
                if item.account == normalized_account and item.status in ACTIVE_STATUSES:
                    item.status = "cancelled"
                    item.code = ""
                    item.detail = ""
            now = self._clock()
            request = PendingOtp(
                request_id=secrets.token_urlsafe(24),
                account=normalized_account,
                created_at=now,
                expires_at=now + ttl,
            )
            self._items[request.request_id] = request
            return request

    def get(self, request_id: str) -> PendingOtp:
        with self._lock:
            self._expire_locked()
            try:
                return self._items[str(request_id)]
            except KeyError as error:
                raise KeyError("unknown request_id") from error

    def _active_for_account_locked(self, account: str) -> list[PendingOtp]:
        normalized_account = str(account or "").strip()
        return [
            item
            for item in self._items.values()
            if item.account == normalized_account and item.status in ACTIVE_STATUSES
        ]

    def has_active_request(self, account: str) -> bool:
        with self._lock:
            self._expire_locked()
            return len(self._active_for_account_locked(account)) == 1

    def mark_auto_attempted(self, *, account: str, detail: str = "") -> str:
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            if item.status == "ready":
                return item.request_id
            item.status = "auto_attempted"
            item.detail = str(detail or "").strip()[:300]
            return item.request_id

    def mark_human_required(self, *, account: str, detail: str = "") -> str:
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            if item.status == "ready":
                return item.request_id
            item.status = "human_required"
            item.detail = str(detail or "").strip()[:300]
            return item.request_id

    def attach_code(self, *, account: str, code: str) -> str:
        normalized_account = str(account or "").strip()
        normalized_code = str(code or "").strip()
        if not normalized_account or not CODE_PATTERN.fullmatch(normalized_code):
            return ""
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(normalized_account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            item.code = normalized_code
            item.detail = ""
            item.status = "ready"
            return item.request_id

    def consume(self, request_id: str) -> str:
        with self._lock:
            item = self.get(request_id)
            if item.status != "ready" or not item.code:
                raise ValueError(f"request is not ready: {item.status}")
            code = item.code
            item.code = ""
            item.detail = ""
            item.status = "consumed"
            return code

    def cancel(self, request_id: str) -> None:
        with self._lock:
            item = self.get(request_id)
            if item.status not in TERMINAL_STATUSES:
                item.status = "cancelled"
                item.code = ""
                item.detail = ""


__all__ = [
    "ACTIVE_STATUSES",
    "PendingOtp",
    "PendingOtpStore",
    "extract_hax_verification_code",
]


extract_verification_code = extract_hax_verification_code
