from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LiveOrder:
    symbol: str
    side: str
    order_type: str
    quantity: float
    quote_amount: float
    price: float
    stop_loss: float
    take_profit: float
    timestamp: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiveValidationResult:
    valid: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiveExecutionResult:
    mode: str
    status: str
    payload: dict[str, object] = field(default_factory=dict)
    reason: str = ""
    order: LiveOrder | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["order"] = self.order.to_dict() if self.order else None
        return data
