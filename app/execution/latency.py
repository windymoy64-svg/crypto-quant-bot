from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LatencyModel:
    candles_delay: int = 0

    def execution_index(self, signal_index: int, last_index: int) -> int:
        return min(signal_index + max(self.candles_delay, 0), last_index)