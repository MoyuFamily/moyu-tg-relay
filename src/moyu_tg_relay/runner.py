"""Portable process entrypoint for direct Python artifact execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main() -> None:
    host = os.environ.get("RELAY_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("RELAY_PORT", "8787") or 8787)
    uvicorn.run(
        "moyu_tg_relay.app:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("RELAY_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
