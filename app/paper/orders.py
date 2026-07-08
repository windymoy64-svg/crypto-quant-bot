from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import count


_paper_order_ids = count(1)


def next_paper_order_id() -> str:
    return f"PAPER-{next(_paper_order_ids):08d}"


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    requested_price: float
    status: str
    created_at: str
    reason: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def paper_order_from_execution(
    *,
    symbol: str,
    side: str,
    quantity: float,
    requested_price: float,
    created_at: str,
    reason: str = "",
    meta: dict[str, object] | None = None,
) -> PaperOrder:
    return PaperOrder(
        order_id=next_paper_order_id(),
        symbol=symbol,
        side=side,
        order_type="MARKET",
        quantity=round(max(quantity, 0.0), 8),
        requested_price=round(max(requested_price, 0.0), 8),
        status="NEW",
        created_at=created_at,
        reason=reason,
        meta=meta or {},
    )