from __future__ import annotations

from dataclasses import asdict, dataclass

from app.execution.order import LiquidityType, OrderStatus


@dataclass(frozen=True)
class SimulatedFill:
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    fee: float
    liquidity: str
    timestamp: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FillResult:
    order_id: str
    status: OrderStatus
    fills: list[SimulatedFill]
    requested_quantity: float
    filled_quantity: float
    average_price: float
    total_notional: float
    total_fee: float
    liquidity: LiquidityType
    reason: str | None = None

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_partial(self) -> bool:
        return self.status == OrderStatus.PARTIALLY_FILLED

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "status": self.status.value,
            "fills": [fill.to_dict() for fill in self.fills],
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "average_price": self.average_price,
            "total_notional": self.total_notional,
            "total_fee": self.total_fee,
            "liquidity": self.liquidity.value,
            "reason": self.reason,
        }