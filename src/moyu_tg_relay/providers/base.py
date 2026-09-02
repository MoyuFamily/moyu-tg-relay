"""Generic provider contract for Telegram interaction routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class IncomingMessage:
    sender_username: str
    sender_id: str
    text: str
    buttons: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ProviderDecision:
    action: str = "ignore"
    code: str = ""
    detail: str = ""
    button: Any | None = None

    @classmethod
    def ignore(cls) -> "ProviderDecision":
        return cls()

    @classmethod
    def code_ready(cls, code: str) -> "ProviderDecision":
        return cls(action="code", code=str(code or "").strip())

    @classmethod
    def click(cls, button: Any, detail: str = "") -> "ProviderDecision":
        return cls(action="click", button=button, detail=detail)

    @classmethod
    def human_required(cls, detail: str) -> "ProviderDecision":
        return cls(action="human_required", detail=str(detail or "").strip())


class TelegramProvider(Protocol):
    name: str

    def evaluate(self, message: IncomingMessage, request: Any) -> ProviderDecision:
        """Evaluate one incoming Telegram message for one active request."""
        ...


__all__ = ["IncomingMessage", "ProviderDecision", "TelegramProvider"]
