#!/usr/bin/env python3
"""Post-deploy smoke check for Moyu Telegram OTP Relay.

Uses only standard library HTTP to verify process liveness and API readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Moyu TG Relay Smoke Check")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OTP_RELAY_BASE_URL", os.environ.get("HAX_OTP_RELAY_URL", "http://127.0.0.1:8787")),
        help="Base URL of the relay service",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("OTP_RELAY_BEARER_TOKEN", os.environ.get("HAX_OTP_RELAY_TOKEN", "")),
        help="Bearer token for protected endpoints",
    )
    args = parser.parse_args()

    base_url = str(args.base_url).strip().rstrip("/")
    token = str(args.token).strip()

    # 1. Healthz check (Liveness)
    status, body = _request(base_url, "/healthz")
    if status != 200 or _json(body).get("status") != "ok":
        print(f"[FAIL] /healthz returned status={status}, body={body}")
        return 1
    print("[PASS] /healthz returned ok")

    # 2. If token is provided, verify /readyz and auth protection
    if token:
        status, body = _request(base_url, "/readyz", token=token)
        if status != 200:
            print(f"[WARN] /readyz returned status={status}, body={body}")
        else:
            print("[PASS] /readyz returned ok")

        status, _ = _request(base_url, "/api/v1/hax-otp/requests", token="invalid-test-token")
        if status != 401:
            print(f"[FAIL] Expected 401 with bad token, got {status}")
            return 1
        print("[PASS] Auth rejection verified (401)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
