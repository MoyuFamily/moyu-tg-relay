#!/usr/bin/env python3
"""Post-deploy smoke check for Moyu Telegram OTP Relay.

Uses only the Python standard library to verify process liveness, Telegram
readiness, and both rejection and acceptance of Bearer authentication without
creating or consuming OTP requests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SMOKE_REQUEST_PATH = "/v1/otp/requests/__moyu_smoke_check_missing__"


def _load_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(path).expanduser()
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"unable to read env file {env_path}: {error}") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RuntimeError(
                f"invalid env file line {line_number}: expected KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not _ENV_KEY.fullmatch(key):
            raise RuntimeError(f"invalid env key on line {line_number}: {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _request(base_url: str, path: str, *, token: str = "") -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{base_url}{path}", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise RuntimeError(f"relay request failed: {error}") from error


def _json(body: str) -> dict:
    try:
        return json.loads(body)
    except Exception:
        return {}


def _setting(
    cli_value: str | None,
    file_values: dict[str, str],
    primary: str,
    fallback: str,
    default: str,
) -> str:
    if cli_value is not None:
        return cli_value
    if primary in os.environ:
        return os.environ[primary]
    if fallback in os.environ:
        return os.environ[fallback]
    if primary in file_values:
        return file_values[primary]
    if fallback in file_values:
        return file_values[fallback]
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Moyu TG Relay Smoke Check")
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional literal KEY=VALUE env file; values are not shell-evaluated",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL of the relay service",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token for protected endpoints",
    )
    args = parser.parse_args()

    file_values = _load_env_file(args.env_file) if args.env_file else {}
    base_url = _setting(
        args.base_url,
        file_values,
        "OTP_RELAY_BASE_URL",
        "HAX_OTP_RELAY_URL",
        "http://127.0.0.1:8787",
    ).strip().rstrip("/")
    token = _setting(
        args.token,
        file_values,
        "OTP_RELAY_BEARER_TOKEN",
        "HAX_OTP_RELAY_TOKEN",
        "",
    ).strip()

    status, body = _request(base_url, "/healthz")
    if status != 200 or _json(body).get("status") != "ok":
        print(f"[FAIL] /healthz returned status={status}, body={body}")
        return 1
    print("[PASS] /healthz returned ok")

    if token:
        status, body = _request(base_url, "/readyz", token=token)
        if status != 200 or _json(body).get("status") != "ready":
            print(f"[FAIL] /readyz returned status={status}, body={body}")
            return 1
        print("[PASS] /readyz returned ready")

        status, _ = _request(
            base_url,
            _SMOKE_REQUEST_PATH,
            token="invalid-test-token",
        )
        if status != 401:
            print(f"[FAIL] Expected 401 with bad token, got {status}")
            return 1
        print("[PASS] Auth rejection verified (401)")

        # The same nonexistent request must pass authentication with the supplied
        # token and reach the handler, which then returns 404 without side effects.
        status, _ = _request(base_url, _SMOKE_REQUEST_PATH, token=token)
        if status != 404:
            print(f"[FAIL] Expected 404 with valid token, got {status}")
            return 1
        print("[PASS] Auth acceptance verified (404 after handler lookup)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
