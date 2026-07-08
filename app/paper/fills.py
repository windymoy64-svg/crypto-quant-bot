from __future__ import annotations

from dataclasses import asdict, dataclass

from app.execution.fill import FillResult


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    execution_order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    fee: float
    status: str
    timestamp: str

    @classmethod
    def from_fill_result(cls, paper_order_id: str, result: FillResult) -> "PaperFill | None":
        if result.filled_quantity <= 0 or not result.fills:
            return None
        fill = result.fills[-1]
        return cls(
            order_id=paper_order_id,
            execution_order_id=result.order_id,
            symbol=fill.symbol,
            side=fill.side,
            quantity=round(result.filled_quantity, 8),
            price=round(result.average_price, 8),
            notional=round(result.total_notional, 8),
            fee=round(result.total_fee, 8),
            status=result.status.value,
            timestamp=fill.timestamp,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)