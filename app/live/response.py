from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OrderSubmissionResult:
    success: bool
    order_id: int | None = None
    client_order_id: str = ""
    symbol: str = ""
    status: str = ""
    executed_qty: float = 0.0
    orig_qty: float = 0.0
    price: float = 0.0
    transact_time: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def blocked(cls, reason: str, raw: dict[str, Any] | None = None) -> "OrderSubmissionResult":
        payload = dict(raw or {})
        payload.setdefault("reason", reason)
        return cls(success=False, status="BLOCKED", raw=payload)

    @classmethod
    def from_binance(cls, data: dict[str, Any]) -> "OrderSubmissionResult":
        return cls(
            success=True,
            order_id=int(data["orderId"]) if data.get("orderId") is not None else None,
            client_order_id=str(data.get("clientOrderId", "")),
            symbol=str(data.get("symbol", "")),
            status=str(data.get("status", "")),
            executed_qty=float(data.get("executedQty") or 0.0),
            orig_qty=float(data.get("origQty") or 0.0),
            price=float(data.get("price") or 0.0),
            transact_time=int(data.get("transactTime") or 0),
            raw=data,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)