"""Spend ledger with a hard cap, checked before every model call.

Before each call the caller asks `reserve(estimate)`. The estimate is the worst case for that call:
every prompt token at the full input rate plus the maximum completion. If the money already spent
plus the estimate would pass the cap, the call is refused (BudgetExceeded) and nothing is sent.
After the call, `record` writes the measured cost. The ledger file is append-only JSON lines, so
the cap holds across runs and restarts.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class SpendLedger:
    def __init__(self, path: str | Path, cap_usd: float):
        self.path, self.cap = Path(path), float(cap_usd)
        self._lock = threading.Lock()
        self._reserved = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def spent(self) -> float:
        if not self.path.exists():
            return 0.0
        return round(sum(json.loads(l).get("cost_usd", 0.0) for l in self.path.read_text().splitlines() if l.strip()), 6)

    def reserve(self, estimate_usd: float, tag: str = "") -> float:
        with self._lock:
            total = self.spent() + self._reserved + estimate_usd
            if total > self.cap:
                raise BudgetExceeded(f"refused {tag}: spent+reserved+worst case ${total:.4f} would pass the ${self.cap:.2f} cap")
            self._reserved += estimate_usd
            return estimate_usd

    def record(self, reserved_usd: float, cost_usd: float, **info) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved_usd)
            with open(self.path, "a") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "cost_usd": round(cost_usd, 6), **info}) + "\n")
