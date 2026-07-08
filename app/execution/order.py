from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class LiquidityType(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


@dataclass(frozen=True)
class OrderLifecycleEvent:
    timestamp: str
    status: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class SimulatedOrder:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    requested_price: float
    created_at: str
    liquidity: LiquidityType = LiquidityType.TAKER
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    events: list[OrderLifecycleEvent] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)

    def add_event(self, timestamp: str, status: OrderStatus, message: str) -> None:
        self.status = status
        self.events.append(OrderLifecycleEvent(timestamp=timestamp, status=status.value, message=message))

    def apply_fill(self, quantity: float, price: float, timestamp: str) -> None:
        previous_notional = self.average_fill_price * self.filled_quantity
        new_notional = price * quantity
        self.filled_quantity += quantity
        self.average_fill_price = (previous_notional + new_notional) / self.filled_quantity if self.filled_quantity else 0.0
        status = OrderStatus.FILLED if self.remaining_quantity <= 0 else OrderStatus.PARTIALLY_FILLED
        self.add_event(timestamp, status, f"filled {quantity:g} at {price:g}")

    def reject(self, timestamp: str, reason: str) -> None:
        self.add_event(timestamp, OrderStatus.REJECTED, reason)

    def cancel(self, timestamp: str, reason: str) -> None:
        self.add_event(timestamp, OrderStatus.CANCELLED, reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "requested_price": self.requested_price,
            "created_at": self.created_at,
            "liquidity": self.liquidity.value,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "remaining_quantity": self.remaining_quantity,
            "average_fill_price": self.average_fill_price,
            "events": [event.to_dict() for event in self.events],
        }