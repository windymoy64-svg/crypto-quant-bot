from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    entry_side: str
    exit_side: str
    quantity: float
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_percent: float
    exit_reason: str

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)