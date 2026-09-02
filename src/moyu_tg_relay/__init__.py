"""moyu-tg-relay: provider-driven Telegram interaction relay."""

from .store import PendingOtp, PendingOtpStore

__all__ = ["PendingOtp", "PendingOtpStore"]
__version__ = "0.1.0"
