from __future__ import annotations

from dataclasses import dataclass

from app.execution.order import OrderSide


@dataclass(frozen=True)
class SpreadModel:
    spread_basis_points: float = 2.0

    def apply(self, mid_price: float, side: OrderSide) -> float:
        half_spread = self.spread_basis_points / 20_000
        if side == OrderSide.BUY:
            return mid_price * (1 + half_spread)
        return mid_price * (1 - half_spread)


@dataclass(frozen=True)
class SlippageModel:
    slippage_basis_points: float = 5.0

    def apply(self, price: float, side: OrderSide) -> float:
        adjustment = self.slippage_basis_points / 10_000
        if side == OrderSide.BUY:
            return price * (1 + adjustment)
        return price * (1 - adjustment)