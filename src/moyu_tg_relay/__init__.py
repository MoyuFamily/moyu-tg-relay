"""moyu-tg-relay: Lightweight & secure Telegram 2FA/OTP relay microservice."""

from .store import (
    PendingOtp,
    PendingOtpStore,
    extract_hax_verification_code,
    extract_verification_code,
)

__all__ = [
    "PendingOtp",
    "PendingOtpStore",
    "extract_hax_verification_code",
    "extract_verification_code",
]
__version__ = "0.1.0"
