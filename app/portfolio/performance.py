from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PortfolioPerformance:
    initial_balance: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def roi_percent(self) -> float:
        return (self.total_pnl / self.initial_balance) * 100 if self.initial_balance else 0.0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["total_pnl"] = round(self.total_pnl, 8)
        data["roi_percent"] = round(self.roi_percent, 4)
        return data