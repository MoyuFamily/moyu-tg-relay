"""Generic Telegram Bot Interaction engine and persistent task store.

Provides decoupled, asynchronous, and proxy-resilient bot interaction capabilities:
- Initiates interactions by sending a command or targeting an existing chat.
- Matches and clicks inline buttons using exact, substring, candidate list, or regex.
- Awaits responses and subsequent results (accommodating slow bots with long timeouts).
- Records all raw messages, buttons, and state transitions for downstream decision-making.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BotInteraction:
    interaction_id: str
    account: str
    bot: str
    command: str | None = None
    action: str | list[str] | None = None
    wait_response_timeout: float = 30.0
    wait_result_timeout: float = 60.0
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: str = "pending"  # pending, in_progress, completed, timeout, failed, cancelled
    stage: str = "init"      # init, waiting_response, action_clicked, waiting_result, done
    command_sent: str | None = None
    initial_message: dict[str, Any] | None = None
    action_clicked: str | None = None
    result_message: dict[str, Any] | None = None
    available_buttons: list[str] = field(default_factory=list)
    error: str | None = None
    context: dict[str, str] = field(default_factory=dict)


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Serialize a Telethon Message into a clean, JSON-serializable dictionary."""
    if msg is None:
        return {}

    buttons: list[str] = []
    rows = getattr(msg, "buttons", None) or []
    for row in rows:
        for b in (row or []):
            t = getattr(b, "text", "")
            if t:
                buttons.append(str(t).strip())

    msg_date = getattr(msg, "date", None)
    iso_date = msg_date.isoformat() if hasattr(msg_date, "isoformat") else None

    return {
        "id": getattr(msg, "id", 0),
        "text": getattr(msg, "raw_text", getattr(msg, "text", "")) or "",
        "buttons": buttons,
        "date": iso_date,
    }


def _find_matching_button(
    buttons: Sequence[Any],
    action: str | Sequence[str] | None,
) -> tuple[Any | None, str | None]:
    """Match a button against candidate strings, substrings, or regexes in priority order.

    Returns:
        tuple (matched_button_object, matched_button_text)
    """
    if not buttons or not action:
        return None, None

    if isinstance(action, (list, tuple)):
        candidates = [str(c).strip() for c in action if str(c).strip()]
    else:
        candidates = [str(action).strip()] if str(action).strip() else []

    if not candidates:
        return None, None

    # Flatten buttons if nested
    flat_buttons: list[Any] = []
    for item in buttons:
        if isinstance(item, (list, tuple)):
            flat_buttons.extend(item)
        else:
            flat_buttons.append(item)

    for candidate in candidates:
        candidate_lower = candidate.lower()
        # Pre-compile regex if candidate has regex metacharacters
        is_regex = any(ch in candidate for ch in ("|", "^", "$", "(", ")", "[", "]", "*", "+", "?"))
        pattern = None
        if is_regex:
            try:
                pattern = re.compile(candidate, re.IGNORECASE)
            except re.error:
                pattern = None

        for btn in flat_buttons:
            text = str(getattr(btn, "text", "") or "").strip()
            if not text:
                continue

            # 1. Exact match (case-insensitive)
            if text.lower() == candidate_lower:
                return btn, text

            # 2. Substring match
            if candidate_lower in text.lower():
                return btn, text

            # 3. Regex match
            if pattern and pattern.search(text):
                return btn, text

    return None, None


class BotInteractionStore:
    """Thread-safe persistent store for long-lived Bot Interactions."""

    TERMINAL_STATUSES = frozenset({"completed", "timeout", "failed", "cancelled"})
    RETENTION_SECONDS = 1800  # 30 minutes retention after completion

    def __init__(
        self,
        persistence_path: str | Path | None = None,
        *,
        clock=time.time,
    ) -> None:
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._clock = clock
        self._lock = threading.RLock()
        self._items: dict[str, BotInteraction] = {}
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
                    if isinstance(item_dict, dict) and "interaction_id" in item_dict:
                        item = BotInteraction(**item_dict)
                        self._items[item.interaction_id] = item
                self._expire_locked(save=False)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

    def _save_locked(self) -> None:
        if not self._persistence_path:
            return
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(item) for item in self._items.values()]
            tmp_path = self._persistence_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self._persistence_path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

    def _expire_locked(self, *, save: bool = True) -> None:
        now = self._clock()
        changed = False
        stale_ids: list[str] = []
        for i_id, item in self._items.items():
            if item.status in {"pending", "in_progress"} and now >= item.expires_at:
                item.status = "timeout"
                item.error = "interaction_overall_timeout"
                changed = True
            if item.status in self.TERMINAL_STATUSES and now >= item.expires_at + self.RETENTION_SECONDS:
                stale_ids.append(i_id)
        for i_id in stale_ids:
            del self._items[i_id]
            changed = True
        if changed and save:
            self._save_locked()

    def create(
        self,
        *,
        account: str,
        bot: str,
        command: str | None = None,
        action: str | list[str] | None = None,
        wait_response_timeout: float = 30.0,
        wait_result_timeout: float = 60.0,
        context: Mapping[str, Any] | None = None,
    ) -> BotInteraction:
        norm_account = str(account or "").strip()
        norm_bot = str(bot or "").strip().lstrip("@")
        if not norm_account:
            raise ValueError("account is required")
        if not norm_bot:
            raise ValueError("bot is required")

        now = self._clock()
        # Max lifetime: sum of timeouts + 60s buffer
        total_ttl = float(wait_response_timeout) + float(wait_result_timeout) + 60.0
        expires_at = now + max(120.0, total_ttl)

        clean_context: dict[str, str] = {}
        if isinstance(context, Mapping):
            for k, v in context.items():
                if k:
                    clean_context[str(k)[:64]] = str(v)[:300]

        interaction = BotInteraction(
            interaction_id=f"bint_{secrets.token_urlsafe(16)}",
            account=norm_account,
            bot=norm_bot,
            command=str(command).strip() if command is not None else None,
            action=action,
            wait_response_timeout=float(wait_response_timeout),
            wait_result_timeout=float(wait_result_timeout),
            created_at=now,
            expires_at=expires_at,
            status="pending",
            stage="init",
            context=clean_context,
        )

        with self._lock:
            self._expire_locked()
            self._items[interaction.interaction_id] = interaction
            self._save_locked()

        return interaction

    def get(self, interaction_id: str) -> BotInteraction:
        with self._lock:
            self._expire_locked()
            try:
                return self._items[str(interaction_id)]
            except KeyError as error:
                raise KeyError(f"unknown interaction_id: {interaction_id}") from error

    def update(
        self,
        interaction_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        command_sent: str | None = None,
        initial_message: dict[str, Any] | None = None,
        action_clicked: str | None = None,
        result_message: dict[str, Any] | None = None,
        available_buttons: list[str] | None = None,
        error: str | None = None,
    ) -> BotInteraction:
        with self._lock:
            item = self.get(interaction_id)
            if status is not None:
                item.status = status
            if stage is not None:
                item.stage = stage
            if command_sent is not None:
                item.command_sent = command_sent
            if initial_message is not None:
                item.initial_message = initial_message
            if action_clicked is not None:
                item.action_clicked = action_clicked
            if result_message is not None:
                item.result_message = result_message
            if available_buttons is not None:
                item.available_buttons = available_buttons
            if error is not None:
                item.error = error
            self._save_locked()
            return item

    def cancel(self, interaction_id: str) -> BotInteraction:
        with self._lock:
            item = self.get(interaction_id)
            if item.status not in self.TERMINAL_STATUSES:
                item.status = "cancelled"
                item.stage = "cancelled"
                self._save_locked()
            return item
