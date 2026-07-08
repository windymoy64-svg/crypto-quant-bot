from __future__ import annotations

from dataclasses import dataclass, field

from app.events.events import PortfolioUpdated, PositionClosed, PositionOpened
from app.events.publisher import publish
from app.portfolio.account import PortfolioAccount
from app.portfolio.exposure import PortfolioExposure
from app.portfolio.performance import PortfolioPerformance
from app.portfolio.position import PortfolioPosition


@dataclass
class PortfolioManager:
    account: PortfolioAccount
    positions: dict[str, PortfolioPosition] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)

    @classmethod
    def with_cash(cls, initial_balance: float) -> "PortfolioManager":
        return cls(account=PortfolioAccount.with_cash(initial_balance))

    @property
    def available_balance(self) -> float:
        return round(self.account.available_balance, 8)

    @property
    def used_capital(self) -> float:
        return round(sum(position.used_capital for position in self.positions.values()), 8)

    @property
    def open_positions_count(self) -> int:
        return len(self.positions)

    @property
    def realized_pnl(self) -> float:
        return round(self.account.realized_pnl, 8)

    @property
    def unrealized_pnl(self) -> float:
        return round(
            sum(position.unrealized_pnl(self.prices.get(symbol)) for symbol, position in self.positions.items()),
            8,
        )

    @property
    def equity(self) -> float:
        return round(self.account.cash + self.market_value, 8)

    @property
    def market_value(self) -> float:
        return round(sum(position.market_value(self.prices.get(symbol)) for symbol, position in self.positions.items()), 8)

    def update_price(self, symbol: str, price: float) -> None:
        if price > 0:
            self.prices[symbol] = price
            self._publish_portfolio_updated()

    def open_position(self, symbol: str, quantity: float, price: float, fee: float, timestamp: str) -> None:
        notional = max(quantity, 0.0) * max(price, 0.0)
        self.account.balance.reserve(notional + max(fee, 0.0))
        self.prices[symbol] = price
        if symbol not in self.positions:
            self.positions[symbol] = PortfolioPosition(symbol, quantity, price, timestamp, fee)
            publish(PositionOpened(symbol=symbol, quantity=quantity, price=price, fee=fee, timestamp=timestamp))
            self._publish_portfolio_updated(timestamp)
            return

        position = self.positions[symbol]
        combined_quantity = position.quantity + quantity
        if combined_quantity <= 0:
            return
        position.average_entry_price = ((position.average_entry_price * position.quantity) + notional) / combined_quantity
        position.quantity = combined_quantity
        position.entry_fee += fee
        publish(PositionOpened(symbol=symbol, quantity=quantity, price=price, fee=fee, timestamp=timestamp))
        self._publish_portfolio_updated(timestamp)

    def close_position(self, symbol: str, quantity: float, price: float, fee: float, timestamp: str = "") -> float:
        position = self.positions.get(symbol)
        if position is None:
            return 0.0
        closed_quantity = position.reduce(quantity)
        proceeds = closed_quantity * price
        allocated_entry_fee = position.entry_fee * (closed_quantity / (position.quantity + closed_quantity)) if closed_quantity else 0.0
        realized = (price - position.average_entry_price) * closed_quantity - allocated_entry_fee - fee
        position.entry_fee -= allocated_entry_fee
        self.account.balance.release(proceeds - max(fee, 0.0))
        self.account.balance.add_realized_pnl(realized)
        self.prices[symbol] = price
        if position.quantity <= 0:
            self.positions.pop(symbol, None)
        publish(
            PositionClosed(
                symbol=symbol,
                quantity=closed_quantity,
                price=price,
                fee=fee,
                realized_pnl=round(realized, 8),
                timestamp=timestamp,
            )
        )
        self._publish_portfolio_updated(timestamp)
        return round(realized, 8)

    def exposure_per_symbol(self) -> dict[str, dict[str, object]]:
        exposure = PortfolioExposure().by_symbol(self.positions, self.prices, self.equity)
        return {symbol: value.to_dict() for symbol, value in exposure.items()}

    def summary(self) -> dict[str, object]:
        performance = PortfolioPerformance(
            initial_balance=self.account.balance.initial_balance,
            equity=self.equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
        )
        return {
            "account": self.account.to_dict(),
            "equity": self.equity,
            "available_balance": self.available_balance,
            "used_capital": self.used_capital,
            "market_value": self.market_value,
            "open_positions": [position.to_dict(self.prices.get(symbol)) for symbol, position in self.positions.items()],
            "open_positions_count": self.open_positions_count,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "roi_percent": performance.roi_percent,
            "exposure_per_symbol": self.exposure_per_symbol(),
            "performance": performance.to_dict(),
        }

    def _publish_portfolio_updated(self, timestamp: str = "") -> None:
        publish(
            PortfolioUpdated(
                equity=self.equity,
                available_balance=self.available_balance,
                used_capital=self.used_capital,
                open_positions_count=self.open_positions_count,
                timestamp=timestamp,
                portfolio={
                    "equity": self.equity,
                    "available_balance": self.available_balance,
                    "used_capital": self.used_capital,
                    "market_value": self.market_value,
                    "open_positions_count": self.open_positions_count,
                },
            )
        )