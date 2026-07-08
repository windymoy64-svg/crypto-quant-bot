from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.live.exchange_rules import normalize_symbol


ACTIVE_STATUSES = {"OPEN", "NEW", "PENDING", "PREPARED", "PARTIALLY_FILLED"}


@dataclass(frozen=True)
class OrderHistoryEntry:
    symbol: str
    side: str
    timestamp: str
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OrderHistory:
    def __init__(self, entries: list[OrderHistoryEntry] | None = None) -> None:
        self.entries = list(entries or [])

    def add(self, symbol: str, side: str, status: str, timestamp: str | None = None) -> None:
        self.entries.append(
            OrderHistoryEntry(
                symbol=normalize_symbol(symbol),
                side=side.upper(),
                timestamp=timestamp or datetime.now(UTC).isoformat(),
                status=status.upper(),
            )
        )

    def same_symbol_orders(self, symbol: str, side: str | None = None) -> list[OrderHistoryEntry]:
        target = normalize_symbol(symbol)
        target_side = side.upper() if side else None
        return [
            entry
            for entry in self.entries
            if normalize_symbol(entry.symbol) == target and (target_side is None or entry.side == target_side)
        ]

    def active_same_side(self, symbol: str, side: str) -> bool:
        return any(entry.status in ACTIVE_STATUSES for entry in self.same_symbol_orders(symbol, side))

    def count_same_symbol(self, symbol: str) -> int:
        return len(self.same_symbol_orders(symbol))

    def latest_same_side(self, symbol: str, side: str) -> OrderHistoryEntry | None:
        matches = self.same_symbol_orders(symbol, side)
        return matches[-1] if matches else None