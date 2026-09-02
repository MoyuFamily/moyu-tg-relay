"""Provider registry for Telegram interaction handlers."""

from .base import IncomingMessage, ProviderDecision, TelegramProvider
from .hax import HaxProvider


def build_provider_registry() -> dict[str, TelegramProvider]:
    providers: tuple[TelegramProvider, ...] = (HaxProvider.from_env(),)
    return {provider.name: provider for provider in providers}


__all__ = [
    "IncomingMessage",
    "ProviderDecision",
    "TelegramProvider",
    "HaxProvider",
    "build_provider_registry",
]
