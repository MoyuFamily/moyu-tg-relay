"""Post-deploy smoke check for the Hax OTP Relay.

Uses only stdlib HTTP so it can run from the renewal host without adding a new
dependency. The probe never creates or consumes an OTP request.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("HAX_OTP_RELAY_URL", "").strip().rstrip("/")
TOKEN = os.environ.get("HAX_OTP_RELAY_TOKEN", "").strip()


def _request(path: str, *, token: str = "") -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{BASE_URL}{path}", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise RuntimeError(f"relay request failed: {error}") from error


def _json(body: str) -> dict:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"relay returned non-JSON response: {body[:200]!r}") from error
    if not isinstance(value, dict):
        raise RuntimeError("relay returned unexpected JSON payload")
    return value


def main() -> int:
    if not BASE_URL:
        print("HAX_OTP_RELAY_URL is required", file=sys.stderr)
        return 2
    if not TOKEN:
        print("HAX_OTP_RELAY_TOKEN is required", file=sys.stderr)
        return 2

    status_code, body = _request("/healthz")
    if status_code != 200 or _json(body).get("status") != "ok":
        raise RuntimeError(f"liveness probe failed: HTTP {status_code} {body[:200]}")
    print("[relay-check] healthz: ok")

    status_code, body = _request("/readyz")
    if status_code != 200 or _json(body).get("status") != "ready":
        raise RuntimeError(f"readiness probe failed: HTTP {status_code} {body[:200]}")
    print("[relay-check] readyz: ready")

    status_code, body = _request(
        "/v1/otp/requests/smoke-check-does-not-exist",
        token=TOKEN,
    )
    if status_code != 404:
        raise RuntimeError(
            f"authenticated API probe expected HTTP 404, got {status_code}: {body[:200]}"
        )
    print("[relay-check] bearer-authenticated API: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
