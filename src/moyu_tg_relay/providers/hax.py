"""Hax-specific Telegram message and confirmation policy."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from .base import IncomingMessage, ProviderDecision


TOKEN_AFTER_LABEL_PATTERN = re.compile(
    r"(?:your\s+code\s+is|verification\s+code\s+is|your\s+verification\s+code\s+is)[\s:\n\r]+([A-Za-z0-9+/=_-]{16,})",
    re.IGNORECASE,
)
BASE64_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/=_-])([A-Za-z0-9+/=]{24,})(?![A-Za-z0-9+/=_-])"
)
CODE_PATTERN = re.compile(r"(?<!\d)(\d{6,10})(?!\d)")
CODE_HINTS = ("verification", "verify", "code", "renew")
DEFAULT_CONFIRM_BUTTONS = (
    "confirm,approve,authorize,accept,yes,continue,确认,允许,授权,同意,是,登录,确定"
)
PROGRAMMATIC_BUTTON_TYPES = frozenset(
    {"KeyboardButton", "KeyboardButtonCallback", "KeyboardButtonUrlAuth", "MessageButton"}
)


def _csv_values(name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(item.strip() for item in str(raw or "").split(",") if item.strip())


def extract_verification_code(text: str) -> str:
    """Extract one plausible Hax verification code, failing closed on ambiguity."""
    if not text:
        return ""
    normalized = " ".join(str(text or "").split())
    lower = normalized.lower()
    if not any(hint in lower for hint in CODE_HINTS):
        return ""

    # 1. Match explicit "Your Code is \n<token>"
    token_match = TOKEN_AFTER_LABEL_PATTERN.search(text)
    if token_match:
        return token_match.group(1).strip()

    # 2. Check for single plausible Base64 token
    b64_matches = list(dict.fromkeys(BASE64_TOKEN_PATTERN.findall(text)))
    if len(b64_matches) == 1:
        return b64_matches[0]

    # 3. Classical 6-10 digit numeric codes (failing closed if ambiguous)
    candidates = list(dict.fromkeys(CODE_PATTERN.findall(normalized)))
    return candidates[0] if len(candidates) == 1 else ""


def _normalized_button_text(button: Any) -> str:
    return " ".join(str(getattr(button, "text", "") or "").lower().split())


def _button_type_name(button: Any) -> str:
    explicit = str(getattr(button, "kind", "") or "").strip().lower()
    if explicit:
        return explicit
    original = getattr(button, "button", None)
    if original is not None:
        return type(original).__name__
    return type(button).__name__


def _is_programmatically_clickable(button: Any) -> bool:
    kind = _button_type_name(button)
    if kind in {"text", "callback"}:
        return True
    return kind in PROGRAMMATIC_BUTTON_TYPES


@dataclass(frozen=True)
class HaxProvider:
    name: str = "hax"
    bot_username: str = "HaxTG_bot"
    auto_confirm: bool = True
    confirmation_sender_ids: frozenset[str] = frozenset({"777000"})
    confirmation_markers: tuple[str, ...] = ("hax.co.id", "hax")
    auto_confirm_buttons: frozenset[str] = frozenset(
        {
            "confirm",
            "approve",
            "authorize",
            "accept",
            "yes",
            "continue",
            "确认",
            "允许",
            "授权",
            "同意",
            "是",
            "登录",
            "确定",
        }
    )

    @classmethod
    def from_env(cls) -> "HaxProvider":
        auto_confirm = os.environ.get("HAX_AUTO_CONFIRM", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        sender_ids = frozenset(
            item for item in _csv_values("HAX_CONFIRMATION_SENDER_IDS", "777000") if item.isdigit()
        )
        markers = tuple(
            item.lower() for item in _csv_values("HAX_CONFIRMATION_MARKERS", "hax.co.id,hax")
        )
        buttons = frozenset(
            item.lower()
            for item in _csv_values(
                "HAX_AUTO_CONFIRM_BUTTONS",
                DEFAULT_CONFIRM_BUTTONS,
            )
        )
        return cls(
            bot_username=os.environ.get("HAX_TELEGRAM_BOT", "HaxTG_bot").strip().lstrip("@"),
            auto_confirm=auto_confirm,
            confirmation_sender_ids=sender_ids,
            confirmation_markers=markers,
            auto_confirm_buttons=buttons,
        )

    def _matches_confirmation(self, message: IncomingMessage, request: Any) -> bool:
        if not message.buttons:
            return False

        context = getattr(request, "context", {}) or {}
        source = str(context.get("source", "") or "")
        stage = str(context.get("stage", "") or "")
        if source and source != "renew-provider":
            return False
        if stage not in {"", "login", "renew"}:
            return False

        sender_allowed = (
            message.sender_username.lower() == self.bot_username.lower()
            or message.sender_id in self.confirmation_sender_ids
        )
        if not sender_allowed:
            return False

        normalized = " ".join(message.text.lower().split())
        return any(marker in normalized for marker in self.confirmation_markers)

    def evaluate(self, message: IncomingMessage, request: Any) -> ProviderDecision:
        if message.sender_username.lower() == self.bot_username.lower():
            code = extract_verification_code(message.text)
            if code:
                return ProviderDecision.code_ready(code)

        if not self._matches_confirmation(message, request):
            return ProviderDecision.ignore()

        matches = [
            button
            for button in message.buttons
            if _normalized_button_text(button) in self.auto_confirm_buttons
        ]
        if len(matches) != 1:
            return ProviderDecision.human_required(
                "检测到 Hax Telegram 确认卡片，但没有唯一的白名单确认按钮"
            )

        button = matches[0]
        if not self.auto_confirm:
            return ProviderDecision.human_required(
                "检测到 Hax Telegram 确认卡片，但自动确认已关闭"
            )

        if not _is_programmatically_clickable(button):
            kind = _button_type_name(button)
            return ProviderDecision.human_required(
                "检测到 Hax Telegram 确认卡片，但按钮类型 "
                f"{kind or 'unknown'} 不能由 Relay 安全自动执行"
            )

        return ProviderDecision.click(
            button,
            detail="已尝试自动点击 Telegram 确认，等待 Hax 页面继续",
        )


__all__ = ["HaxProvider", "extract_verification_code"]
