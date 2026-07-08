from __future__ import annotations

from datetime import datetime

from app.live.exchange_rules import normalize_symbol


class SymbolCooldown:
    def __init__(self, cooldown_seconds: int = 300) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_seen: dict[str, float] = {}

    def active(self, symbol: str, now: float | None = None) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        current = self._now(now)
        previous = self._last_seen.get(normalize_symbol(symbol))
        return previous is not None and (current - previous) < self.cooldown_seconds

    def mark(self, symbol: str, now: float | None = None) -> None:
        self._last_seen[normalize_symbol(symbol)] = self._now(now)

    def remaining(self, symbol: str, now: float | None = None) -> int:
        current = self._now(now)
        previous = self._last_seen.get(normalize_symbol(symbol))
        if previous is None:
            return 0
        return max(0, int(self.cooldown_seconds - (current - previous)))

    def _now(self, now: float | None) -> float:
        return float(now if now is not None else datetime.now().timestamp())