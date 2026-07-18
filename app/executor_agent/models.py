"""Data models for Executor Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


OrderType = Literal["MARKET", "LIMIT", "STOP_LIMIT", "STOP_MARKET"]
OrderSide = Literal["BUY", "SELL"]
ExecutionStatus = Literal["PENDING", "SUBMITTED", "FILLED", "PARTIAL", "REJECTED", "CANCELLED"]


@dataclass(frozen=True)
class PositionContext:
    """Open-position data required to execute an EXIT decision."""

    side: Literal["BUY", "SELL"]
    quantity: float
    current_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrderRequest:
    """A single order to be sent to the exchange."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None  # for LIMIT/STOP_LIMIT
    stop_price: float | None = None  # for STOP orders
    reduce_only: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    """Result of an order execution attempt."""

    status: ExecutionStatus
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: float
    filled_quantity: float
    average_price: float
    timestamp: str
    reason: str = ""
    fees: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_success(self) -> bool:
        return self.status in ("FILLED", "PARTIAL")


@dataclass
class ExecutionPlan:
    """Complete execution plan for a Decision — may contain multiple orders."""

    decision_action: str
    symbol: str
    orders: list[OrderRequest]
    timestamp: str
    dry_run: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_action": self.decision_action,
            "symbol": self.symbol,
            "orders": [o.to_dict() for o in self.orders],
            "timestamp": self.timestamp,
            "dry_run": self.dry_run,
            "meta": self.meta,
        }


@dataclass
class ExecutionReport:
    """Full report of execution — sent back to Learning Agent."""

    plan: ExecutionPlan
    results: list[ExecutionResult]
    success: bool
    total_filled_quantity: float
    average_entry_price: float
    total_fees: float
    timestamp: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "success": self.success,
            "total_filled_quantity": self.total_filled_quantity,
            "average_entry_price": self.average_entry_price,
            "total_fees": self.total_fees,
            "timestamp": self.timestamp,
            "errors": self.errors,
        }
