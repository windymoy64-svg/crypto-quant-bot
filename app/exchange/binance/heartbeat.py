from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class BinanceHeartbeat:
    interval_seconds: float = 30.0
    stale_after_seconds: float = 90.0
    last_message_at: float = 0.0
    last_ping_at: float = 0.0

    def mark_message(self) -> None:
        self.last_message_at = time.monotonic()

    def should_ping(self) -> bool:
        now = time.monotonic()
        return self.last_ping_at == 0.0 or now - self.last_ping_at >= self.interval_seconds

    def mark_ping(self) -> None:
        self.last_ping_at = time.monotonic()

    def is_stale(self) -> bool:
        if self.last_message_at == 0.0:
            return False
        return time.monotonic() - self.last_message_at >= self.stale_after_seconds