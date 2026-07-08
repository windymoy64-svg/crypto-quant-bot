from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class PortfolioPosition:
    symbol: str
    quantity: float
    average_entry_price: float
    opened_at: str
    entry_fee: float = 0.0

    @property
    def used_capital(self) -> float:
        return max(self.quantity, 0.0) * max(self.average_entry_price, 0.0)

    def market_value(self, price: float | None = None) -> float:
        mark_price = self.average_entry_price if price is None else price
        return max(self.quantity, 0.0) * max(mark_price, 0.0)

    def unrealized_pnl(self, price: float | None = None) -> float:
        mark_price = self.average_entry_price if price is None else price
        return (mark_price - self.average_entry_price) * self.quantity

    def reduce(self, quantity: float) -> float:
        closed_quantity = min(max(quantity, 0.0), self.quantity)
        self.quantity -= closed_quantity
        return closed_quantity

    def to_dict(self, price: float | None = None) -> dict[str, object]:
        data = asdict(self)
        data["used_capital"] = round(self.used_capital, 8)
        data["market_value"] = round(self.market_value(price), 8)
        data["unrealized_pnl"] = round(self.unrealized_pnl(price), 8)
        return data