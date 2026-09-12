from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Union


ACTIVE_STATUSES = frozenset({"pending", "auto_attempted", "human_required", "ready"})
TERMINAL_STATUSES = frozenset({"consumed", "expired", "cancelled"})
TERMINAL_RETENTION_SECONDS = 600


@dataclass
class PendingOtp:
    request_id: str
    provider: str
    account: str
    created_at: float
    expires_at: float
    status: str = "pending"
    code: str = ""
    detail: str = ""
    context: dict[str, str] = field(default_factory=dict)


def _normalize_context(context: Optional[Mapping[str, Any]]) -> dict[str, str]:
    if not isinstance(context, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key, value in context.items():
        normalized_key = str(key or "").strip()[:64]
        if not normalized_key:
            continue
        normalized[normalized_key] = str(value or "").strip()[:300]
    return normalized


class PendingOtpStore:
    """Thread-safe TTL store with one active interaction per Telegram account."""

    def __init__(
        self,
        *,
        clock=time.time,
        persistence_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._items: dict[str, PendingOtp] = {}
        self._persistence_path = Path(persistence_path) if persistence_path else None
        if self._persistence_path:
            with self._lock:
                self._load_locked()

    def _load_locked(self) -> None:
        if not self._persistence_path or not self._persistence_path.is_file():
            return
        try:
            content = self._persistence_path.read_text(encoding="utf-8")
            if not content.strip():
                return
            data = json.loads(content)
            if isinstance(data, list):
                for item_dict in data:
                    if isinstance(item_dict, dict) and "request_id" in item_dict:
                        item = PendingOtp(
                            request_id=str(item_dict["request_id"]),
                            provider=str(item_dict.get("provider", "generic")),
                            account=str(item_dict.get("account", "")),
                            created_at=float(item_dict.get("created_at", 0.0)),
                            expires_at=float(item_dict.get("expires_at", 0.0)),
                            status=str(item_dict.get("status", "pending")),
                            code=str(item_dict.get("code", "")),
                            detail=str(item_dict.get("detail", "")),
                            context=_normalize_context(item_dict.get("context")),
                        )
                        self._items[item.request_id] = item
                self._expire_locked(save=False)
        except Exception:
            pass

    def _save_locked(self) -> None:
        if not self._persistence_path:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(item) for item in self._items.values()]
            tmp_path = self._persistence_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self._persistence_path)
        except Exception:
            pass

    def _expire_locked(self, *, save: bool = True) -> None:
        now = self._clock()
        changed = False
        stale_request_ids: list[str] = []
        for request_id, item in self._items.items():
            if item.status in ACTIVE_STATUSES and now >= item.expires_at:
                item.status = "expired"
                item.code = ""
                item.detail = ""
                changed = True
            if (
                item.status in TERMINAL_STATUSES
                and now >= item.expires_at + TERMINAL_RETENTION_SECONDS
            ):
                stale_request_ids.append(request_id)
        for request_id in stale_request_ids:
            del self._items[request_id]
            changed = True
        if changed and save:
            self._save_locked()

    def create(
        self,
        account: str,
        ttl_seconds: int = 300,
        context: Optional[Mapping[str, Any]] = None,
        *,
        provider: str = "generic",
    ) -> PendingOtp:
        normalized_account = str(account or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_account:
            raise ValueError("account is required")
        if not normalized_provider:
            raise ValueError("provider is required")
        ttl = max(60, min(int(ttl_seconds), 600))
        with self._lock:
            self._expire_locked()
            # One Telegram account can only have one active interaction. This
            # keeps incoming message routing unambiguous across providers.
            for item in self._items.values():
                if item.account == normalized_account and item.status in ACTIVE_STATUSES:
                    item.status = "cancelled"
                    item.code = ""
                    item.detail = ""
            now = self._clock()
            request = PendingOtp(
                request_id=secrets.token_urlsafe(24),
                provider=normalized_provider,
                account=normalized_account,
                created_at=now,
                expires_at=now + ttl,
                context=_normalize_context(context),
            )
            self._items[request.request_id] = request
            self._save_locked()
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

    def active_request(self, account: str) -> Optional[PendingOtp]:
        """Return the sole active interaction for an account, if unambiguous."""
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(account)
            return candidates[0] if len(candidates) == 1 else None

    def has_active_request(self, account: str) -> bool:
        return self.active_request(account) is not None

    def mark_auto_attempted(
        self,
        *,
        account: str,
        detail: str = "",
        request_id: Optional[str] = None,
    ) -> str:
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            if request_id is not None and item.request_id != str(request_id):
                return ""
            if item.status == "ready":
                return item.request_id
            item.status = "auto_attempted"
            item.detail = str(detail or "").strip()[:300]
            self._save_locked()
            return item.request_id

    def mark_human_required(
        self,
        *,
        account: str,
        detail: str = "",
        request_id: Optional[str] = None,
    ) -> str:
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            if request_id is not None and item.request_id != str(request_id):
                return ""
            if item.status == "ready":
                return item.request_id
            item.status = "human_required"
            item.detail = str(detail or "").strip()[:300]
            self._save_locked()
            return item.request_id

    def attach_code(
        self,
        *,
        account: str,
        code: str,
        request_id: Optional[str] = None,
    ) -> str:
        normalized_account = str(account or "").strip()
        normalized_code = str(code or "").strip()
        if not normalized_account or not normalized_code or len(normalized_code) > 128:
            return ""
        with self._lock:
            self._expire_locked()
            candidates = self._active_for_account_locked(normalized_account)
            if len(candidates) != 1:
                return ""
            item = candidates[0]
            if request_id is not None and item.request_id != str(request_id):
                return ""
            item.code = normalized_code
            item.detail = ""
            item.status = "ready"
            self._save_locked()
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
            self._save_locked()
            return code

    def cancel(self, request_id: str) -> None:
        with self._lock:
            item = self.get(request_id)
            if item.status not in TERMINAL_STATUSES:
                item.status = "cancelled"
                item.code = ""
                item.detail = ""
                self._save_locked()


__all__ = ["ACTIVE_STATUSES", "PendingOtp", "PendingOtpStore"]
