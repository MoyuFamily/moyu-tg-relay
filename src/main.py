"""Workload process entrypoint for moyu-tg-relay.

Forwarding to moyu_tg_relay.runner:main to satisfy the canonical
moyu-vps-deploy Python src/ layout contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from moyu_tg_relay.runner import main

if __name__ == "__main__":
    main()
