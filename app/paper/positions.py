from __future__ import annotations

from dataclasses import dataclass

from app.portfolio.position import PortfolioPosition


@dataclass(frozen=True)
class PaperPositionSnapshot:
    symbol: str
    quantity: float
    average_entry_price: float
    opened_at: str
    entry_fee: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PaperPositionSnapshot":
        return cls(
            symbol=str(data["symbol"]),
            quantity=float(data.get("quantity", 0.0)),
            average_entry_price=float(data.get("average_entry_price", 0.0)),
            opened_at=str(data.get("opened_at", "")),
            entry_fee=float(data.get("entry_fee", 0.0)),
        )

    @classmethod
    def from_portfolio(cls, position: PortfolioPosition) -> "PaperPositionSnapshot":
        return cls(
            symbol=position.symbol,
            quantity=position.quantity,
            average_entry_price=position.average_entry_price,
            opened_at=position.opened_at,
            entry_fee=position.entry_fee,
        )

    def to_portfolio_position(self) -> PortfolioPosition:
        return PortfolioPosition(
            symbol=self.symbol,
            quantity=self.quantity,
            average_entry_price=self.average_entry_price,
            opened_at=self.opened_at,
            entry_fee=self.entry_fee,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "quantity": round(self.quantity, 8),
            "average_entry_price": round(self.average_entry_price, 8),
            "opened_at": self.opened_at,
            "entry_fee": round(self.entry_fee, 8),
        }