from __future__ import annotations

from dataclasses import dataclass

from app.execution.order import LiquidityType


@dataclass(frozen=True)
class FeeModel:
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.001

    def rate_for(self, liquidity: LiquidityType) -> float:
        return self.maker_fee_rate if liquidity == LiquidityType.MAKER else self.taker_fee_rate

    def calculate(self, notional: float, liquidity: LiquidityType) -> float:
        return max(notional, 0.0) * self.rate_for(liquidity)