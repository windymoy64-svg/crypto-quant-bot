from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.live.order_state import OrderState, normalize_order_state
from app.live.response import OrderSubmissionResult


@dataclass
class LiveOrderRecord:
    order_id: int | None
    client_order_id: str
    symbol: str
    status: OrderState
    filled_qty: float
    remaining_qty: float
    average_price: float
    create_time: str
    update_time: str
    raw: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_submission(cls, result: OrderSubmissionResult, timestamp: str | None = None) -> "LiveOrderRecord":
        now = timestamp or datetime.now(UTC).isoformat()
        remaining = max(result.orig_qty - result.executed_qty, 0.0)
        return cls(
            order_id=result.order_id,
            client_order_id=result.client_order_id,
            symbol=result.symbol,
            status=normalize_order_state(result.status),
            filled_qty=result.executed_qty,
            remaining_qty=remaining,
            average_price=result.price,
            create_time=now,
            update_time=now,
            raw=dict(result.raw),
        )

    def update_from_payload(self, payload: dict[str, object], timestamp: str | None = None) -> None:
        self.status = normalize_order_state(str(payload.get("status", self.status.value)))
        orig_qty = _safe_float(payload.get("origQty"), self.filled_qty + self.remaining_qty)
        self.filled_qty = _safe_float(payload.get("executedQty"), self.filled_qty)
        self.remaining_qty = max(orig_qty - self.filled_qty, 0.0)
        self.average_price = _average_price(payload, self.average_price, self.filled_qty)
        self.update_time = timestamp or datetime.now(UTC).isoformat()
        self.raw = dict(payload)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class OrderStore:
    def __init__(self, records: list[LiveOrderRecord] | None = None) -> None:
        self._records: dict[str, LiveOrderRecord] = {}
        for record in records or []:
            self.upsert(record)

    def add_submission(self, result: OrderSubmissionResult, timestamp: str | None = None) -> LiveOrderRecord:
        record = LiveOrderRecord.from_submission(result, timestamp)
        self.upsert(record)
        return record

    def upsert(self, record: LiveOrderRecord) -> LiveOrderRecord:
        self._records[self._key(record.order_id, record.client_order_id)] = record
        return record

    def update(self, order_id: int | None, client_order_id: str, payload: dict[str, object], timestamp: str | None = None) -> LiveOrderRecord:
        record = self.get(order_id, client_order_id)
        if record is None:
            record = LiveOrderRecord(
                order_id=order_id,
                client_order_id=client_order_id,
                symbol=str(payload.get("symbol", "")),
                status=normalize_order_state(str(payload.get("status", "REJECTED"))),
                filled_qty=0.0,
                remaining_qty=0.0,
                average_price=0.0,
                create_time=timestamp or datetime.now(UTC).isoformat(),
                update_time=timestamp or datetime.now(UTC).isoformat(),
            )
            self.upsert(record)
        record.update_from_payload(payload, timestamp)
        return record

    def get(self, order_id: int | None, client_order_id: str = "") -> LiveOrderRecord | None:
        return self._records.get(self._key(order_id, client_order_id))

    def open_orders(self) -> list[LiveOrderRecord]:
        return [record for record in self._records.values() if record.status in {OrderState.NEW, OrderState.PARTIALLY_FILLED}]

    def filled_orders(self) -> list[LiveOrderRecord]:
        return [record for record in self._records.values() if record.status == OrderState.FILLED]

    def rejected_orders(self) -> list[LiveOrderRecord]:
        return [record for record in self._records.values() if record.status == OrderState.REJECTED]

    def history(self) -> list[LiveOrderRecord]:
        return list(self._records.values())

    def dashboard_snapshot(self) -> dict[str, object]:
        return {
            "open_orders": [record.to_dict() for record in self.open_orders()],
            "filled_orders": [record.to_dict() for record in self.filled_orders()],
            "rejected_orders": [record.to_dict() for record in self.rejected_orders()],
            "order_history": [record.to_dict() for record in self.history()],
        }

    def _key(self, order_id: int | None, client_order_id: str) -> str:
        return str(order_id) if order_id is not None else f"client:{client_order_id}"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _average_price(payload: dict[str, object], default: float, filled_qty: float) -> float:
    explicit_price = _safe_float(payload.get("price"), default)
    if explicit_price > 0:
        return explicit_price
    quote_qty = _safe_float(payload.get("cummulativeQuoteQty"), 0.0)
    if quote_qty > 0 and filled_qty > 0:
        return quote_qty / filled_qty
    return default