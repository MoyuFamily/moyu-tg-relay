"""Telegram account configuration, identity and runtime helpers.

The relay keeps configuration parsing independent from the FastAPI module so
bootstrap and tests can validate an explicit environment mapping without
importing a running application.  Secrets are deliberately excluded from the
``repr`` of all configuration objects.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_account_id(value: Any) -> str:
    """Return a canonical positive Telegram user id or raise ``ValueError``."""

    if isinstance(value, bool):
        raise ValueError("account_id must be a Telegram numeric ID")
    raw = _text(value)
    if not raw or not raw.isdigit() or int(raw) <= 0:
        raise ValueError("account_id must be a Telegram numeric ID")
    return str(int(raw))


def normalize_username(value: Any) -> str:
    return _text(value).lstrip("@").lower()


def normalize_phone(value: Any) -> str:
    """Normalize a phone alias only when its input has phone-like syntax.

    Returning an empty string for arbitrary text is important: extracting
    digits from ``"user123"`` would otherwise make unrelated usernames match.
    """

    raw = _text(value)
    if not raw:
        return ""
    if raw.startswith("+"):
        body = raw[1:]
    else:
        body = raw
    # Telegram phone input commonly includes spaces, dashes, parentheses or
    # dots.  Letters and other punctuation make it a username/opaque alias.
    if not body or any(char not in "0123456789 -()." for char in body):
        return ""
    digits = "".join(char for char in body if char.isdigit())
    return digits if len(digits) >= 7 else ""


def normalize_session_path(value: Any) -> str:
    """Normalize a Telethon SQLite session path for duplicate detection.

    Telethon appends ``.session`` to paths without that suffix.  Comparing the
    effective absolute path catches ``foo`` and ``foo.session`` as duplicates.
    """

    raw = _text(value)
    if not raw:
        return ""
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=False)
    except OSError:
        path = Path(os.path.abspath(str(path)))
    if path.suffix.lower() != ".session":
        path = Path(str(path) + ".session")
    return str(path)


@dataclass(frozen=True)
class AccountConfig:
    """Validated static configuration for one Telegram account."""

    account_id: str
    api_id: int
    api_hash: str = field(repr=False)
    session_string: str = field(default="", repr=False)
    session_path: str = ""
    phone: str = ""
    username: str = ""

    @property
    def session_mode(self) -> str:
        return "string" if self.session_string else "file"

    @property
    def normalized_session_path(self) -> str:
        return normalize_session_path(self.session_path)

    def __repr__(self) -> str:  # pragma: no cover - exercised indirectly
        return (
            "AccountConfig("
            f"account_id={self.account_id!r}, api_id={self.api_id!r}, "
            f"session_mode={self.session_mode!r}, session_path={self.session_path!r}, "
            f"phone={self.phone!r}, username={self.username!r})"
        )


@dataclass(frozen=True)
class AccountIdentity:
    """Runtime identity returned by Telegram, plus configured aliases."""

    account_id: str
    phone: str = ""
    username: str = ""
    alias_phone: str = ""
    alias_username: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", normalize_account_id(self.account_id))
        object.__setattr__(self, "phone", _text(self.phone))
        object.__setattr__(self, "username", normalize_username(self.username))
        object.__setattr__(self, "alias_phone", _text(self.alias_phone))
        object.__setattr__(self, "alias_username", normalize_username(self.alias_username))

    @property
    def phone_aliases(self) -> tuple[str, ...]:
        return tuple(
            item
            for item in (self.phone, self.alias_phone)
            if item
        )

    @property
    def username_aliases(self) -> tuple[str, ...]:
        return tuple(
            item
            for item in (self.username, self.alias_username)
            if item
        )


@dataclass
class AccountRuntime:
    """Mutable runtime state for one account.

    Each account owns its client, identity and asyncio lock.  ``status`` is a
    short operational state used by admin/readiness reporting; readiness is
    still checked against the client so a dropped connection is observed.
    """

    config: AccountConfig
    client: Any = None
    identity: Optional[AccountIdentity] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    status: str = "not_ready"
    error: str = field(default="", repr=False)

    @property
    def account_id(self) -> str:
        return self.config.account_id

    @property
    def session_mode(self) -> str:
        return self.config.session_mode

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            "AccountRuntime("
            f"account_id={self.account_id!r}, status={self.status!r}, "
            f"session_mode={self.session_mode!r}, client={type(self.client).__name__!r})"
        )


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Any:
    return mapping.get(key)


def _parse_api_id(value: Any, *, account_id: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"account {account_id}: api_id is invalid")
    raw = _text(value)
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"account {account_id}: api_id is invalid") from error
    if parsed <= 0:
        raise ValueError(f"account {account_id}: api_id is invalid")
    return parsed


def _parse_item(
    item: Any,
    *,
    index: int,
    global_api_id: Any,
    global_api_hash: Any,
) -> AccountConfig:
    if not isinstance(item, Mapping):
        raise ValueError(f"account entry {index} must be an object")
    try:
        account_id = normalize_account_id(_mapping_value(item, "account_id"))
    except ValueError as error:
        raise ValueError(f"account entry {index}: {error}") from error

    api_raw = _mapping_value(item, "api_id")
    if api_raw is None or _text(api_raw) == "":
        api_raw = global_api_id
    api_id = _parse_api_id(api_raw, account_id=account_id)

    api_hash = _text(_mapping_value(item, "api_hash"))
    if not api_hash:
        api_hash = _text(global_api_hash)
    if not api_hash:
        raise ValueError(f"account {account_id}: api_hash is required")

    session_string = _text(_mapping_value(item, "session_string"))
    session_path = _text(_mapping_value(item, "session_path"))
    if not session_string and not session_path:
        raise ValueError(f"account {account_id}: session_string or session_path is required")

    return AccountConfig(
        account_id=account_id,
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        session_path=session_path,
        phone=_text(_mapping_value(item, "phone")),
        username=normalize_username(_mapping_value(item, "username")),
    )


def _validate_duplicates(configs: Sequence[AccountConfig]) -> None:
    ids: set[str] = set()
    session_strings: set[str] = set()
    session_paths: set[str] = set()
    for config in configs:
        if config.account_id in ids:
            raise ValueError("duplicate account_id in TELEGRAM_ACCOUNTS_JSON")
        ids.add(config.account_id)
        if config.session_string:
            if config.session_string in session_strings:
                raise ValueError("duplicate session_string in TELEGRAM_ACCOUNTS_JSON")
            session_strings.add(config.session_string)
        if config.session_path:
            normalized = config.normalized_session_path
            if normalized in session_paths:
                raise ValueError("duplicate session_path in TELEGRAM_ACCOUNTS_JSON")
            session_paths.add(normalized)


def _legacy_config(
    env: Mapping[str, Any],
    *,
    legacy_session_path: Optional[str] = None,
) -> AccountConfig:
    account_id = normalize_account_id(env.get("TELEGRAM_ACCOUNT_ID"))
    api_id = _parse_api_id(env.get("TELEGRAM_API_ID"), account_id=account_id)
    api_hash = _text(env.get("TELEGRAM_API_HASH"))
    if not api_hash:
        raise ValueError(f"account {account_id}: api_hash is required")
    session_string = _text(env.get("TELEGRAM_SESSION_STRING"))
    session_path = _text(env.get("TELEGRAM_SESSION_PATH"))
    if not session_path:
        session_path = _text(legacy_session_path)
    if not session_string and not session_path:
        state_dir = _text(env.get("STATE_DIR")) or ".state"
        session_path = str(Path(state_dir) / "telegram.session")
    return AccountConfig(
        account_id=account_id,
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        session_path=session_path,
        phone=_text(env.get("TELEGRAM_PHONE")),
        username=normalize_username(env.get("TELEGRAM_USERNAME")),
    )


def load_account_configs(
    env: Optional[Mapping[str, Any]] = None,
    *,
    legacy_session_path: Optional[str] = None,
) -> tuple[AccountConfig, ...]:
    """Load validated account configs from an explicit env mapping.

    If ``TELEGRAM_ACCOUNTS_JSON`` is present (even if malformed or empty), it
    is authoritative and no legacy fallback is attempted.  A missing/blank
    value uses the existing single-account ``TELEGRAM_*`` settings.
    """

    source: Mapping[str, Any] = env if env is not None else os.environ
    raw = source.get("TELEGRAM_ACCOUNTS_JSON")
    if raw is not None and _text(raw):
        try:
            parsed = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("TELEGRAM_ACCOUNTS_JSON is invalid JSON") from error
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("TELEGRAM_ACCOUNTS_JSON must be a non-empty array")
        global_api_id = source.get("TELEGRAM_API_ID")
        global_api_hash = source.get("TELEGRAM_API_HASH")
        configs = tuple(
            _parse_item(
                item,
                index=index,
                global_api_id=global_api_id,
                global_api_hash=global_api_hash,
            )
            for index, item in enumerate(parsed)
        )
        _validate_duplicates(configs)
        return configs

    return (_legacy_config(source, legacy_session_path=legacy_session_path),)


# Keep intuitive aliases for callers that used the noun-first spelling while
# the implementation settles on ``load_account_configs``.
parse_account_configs = load_account_configs
load_accounts = load_account_configs


def make_runtime(config: AccountConfig, *, client: Any = None) -> AccountRuntime:
    return AccountRuntime(config=config, client=client)


def identity_from_me(
    config: AccountConfig,
    me: Any,
) -> AccountIdentity:
    """Build an identity while retaining configured aliases as fallbacks."""

    return AccountIdentity(
        account_id=config.account_id,
        phone=_text(getattr(me, "phone", "")) or config.phone,
        username=normalize_username(getattr(me, "username", "")) or config.username,
        alias_phone=config.phone,
        alias_username=config.username,
    )


def identity_from_config(config: AccountConfig) -> AccountIdentity:
    return AccountIdentity(
        account_id=config.account_id,
        phone=config.phone,
        username=config.username,
        alias_phone=config.phone,
        alias_username=config.username,
    )


def matching_account_ids(
    supplied: Any,
    identities: Sequence[AccountIdentity],
) -> tuple[str, ...]:
    """Return canonical IDs matched by an ID, phone or username alias."""
    target = _text(supplied)
    if not target:
        return ()
    target_id = str(int(target)) if target.isdigit() else target
    exact = sorted({item.account_id for item in identities if item.account_id == target_id})
    if exact:
        return tuple(exact)
    phone = normalize_phone(target)
    if phone:
        matches = {
            item.account_id
            for item in identities
            if any(
                phone == normalize_phone(alias)
                or (
                    len(phone) >= 8
                    and len(normalize_phone(alias)) >= 8
                    and (
                        phone.endswith(normalize_phone(alias))
                        or normalize_phone(alias).endswith(phone)
                    )
                )
                for alias in item.phone_aliases
                if normalize_phone(alias)
            )
        }
        return tuple(sorted(matches))
    username = normalize_username(target)
    return tuple(sorted({
        item.account_id
        for item in identities
        if username and username in item.username_aliases
    }))


__all__ = [
    "AccountConfig",
    "AccountIdentity",
    "AccountRuntime",
    "identity_from_config",
    "identity_from_me",
    "load_account_configs",
    "load_accounts",
    "make_runtime",
    "matching_account_ids",
    "normalize_account_id",
    "normalize_phone",
    "normalize_session_path",
    "normalize_username",
    "parse_account_configs",
]
