"""Woiden-specific Telegram message and confirmation policy."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .hax import (
    DEFAULT_CONFIRM_BUTTONS,
    HaxProvider,
    _csv_values,
    extract_verification_code,
)


@dataclass(frozen=True)
class WoidenProvider(HaxProvider):
    name: str = "woiden"
    bot_username: str = "HaxTG_bot"
    auto_confirm: bool = True
    confirmation_sender_ids: frozenset[str] = frozenset({"777000"})
    confirmation_markers: tuple[str, ...] = ("woiden.id", "woiden", "hax.co.id", "hax")

    @classmethod
    def from_env(cls) -> "WoidenProvider":
        auto_confirm_val = (
            os.environ.get("WOIDEN_AUTO_CONFIRM")
            or os.environ.get("HAX_AUTO_CONFIRM", "true")
        ).strip().lower()
        auto_confirm = auto_confirm_val not in {"0", "false", "no", "off"}

        sender_ids_val = (
            os.environ.get("WOIDEN_CONFIRMATION_SENDER_IDS")
            or os.environ.get("HAX_CONFIRMATION_SENDER_IDS", "777000")
        )
        sender_ids = frozenset(
            item
            for item in (i.strip() for i in sender_ids_val.split(",") if i.strip())
            if item.isdigit()
        )

        markers_raw = os.environ.get(
            "WOIDEN_CONFIRMATION_MARKERS",
            "woiden.id,woiden,hax.co.id,hax",
        )
        markers = tuple(
            item.lower()
            for item in (i.strip() for i in markers_raw.split(",") if i.strip())
        )

        buttons_raw = (
            os.environ.get("WOIDEN_AUTO_CONFIRM_BUTTONS")
            or os.environ.get("HAX_AUTO_CONFIRM_BUTTONS", DEFAULT_CONFIRM_BUTTONS)
        )
        buttons = frozenset(
            item.lower()
            for item in (i.strip() for i in buttons_raw.split(",") if i.strip())
        )

        bot_username = (
            os.environ.get("WOIDEN_TELEGRAM_BOT")
            or os.environ.get("HAX_TELEGRAM_BOT", "HaxTG_bot")
        ).strip().lstrip("@")

        return cls(
            bot_username=bot_username,
            auto_confirm=auto_confirm,
            confirmation_sender_ids=sender_ids,
            confirmation_markers=markers,
            auto_confirm_buttons=buttons,
        )


__all__ = ["WoidenProvider"]
