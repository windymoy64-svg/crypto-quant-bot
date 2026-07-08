from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BinanceReconnectPolicy:
    max_attempts: int = 0
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    backoff_factor: float = 2.0

    def should_retry(self, attempt: int) -> bool:
        return self.max_attempts <= 0 or attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        delay = self.initial_delay_seconds * (self.backoff_factor ** max(attempt - 1, 0))
        return min(delay, self.max_delay_seconds)