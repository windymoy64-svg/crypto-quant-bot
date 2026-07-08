from __future__ import annotations

from typing import Protocol

from app.analytics.journal import TradeJournal, TradeJournalEntry
from app.events.bus import EventBus, event_bus
from app.live.order_events import OrderCanceled, OrderCreated, OrderExpired, OrderFilled, OrderPartiallyFilled, OrderRejected
from app.live.order_state import OrderState
from app.live.order_store import LiveOrderRecord, OrderStore
from app.live.response import OrderSubmissionResult


class OrderMonitorProtocol(Protocol):
    def order_status(self, symbol: str, order_id: int | None = None, client_order_id: str | None = None) -> dict[str, object]:
        ...


class LiveOrderLifecycleManager:
    def __init__(
        self,
        store: OrderStore | None = None,
        *,
        monitor: OrderMonitorProtocol | None = None,
        bus: EventBus | None = None,
        portfolio: object | None = None,
        journal: TradeJournal | None = None,
    ) -> None:
        self.store = store or OrderStore()
        self.monitor = monitor
        self.bus = bus or event_bus
        self.portfolio = portfolio
        self.journal = journal
        self._synced_filled_orders: set[str] = set()

    def on_submission(self, result: OrderSubmissionResult) -> LiveOrderRecord:
        record = self.store.add_submission(result)
        self._publish_for_state(record, created=True)
        self._sync_side_effects(record)
        return record

    def refresh(self, order_id: int | None, client_order_id: str = "") -> LiveOrderRecord:
        record = self.store.get(order_id, client_order_id)
        if record is None:
            raise KeyError("order_not_found")
        if self.monitor is None:
            return record
        payload = self.monitor.order_status(record.symbol, order_id=record.order_id, client_order_id=record.client_order_id)
        updated = self.store.update(record.order_id, record.client_order_id, payload)
        self._publish_for_state(updated)
        self._sync_side_effects(updated)
        return updated

    def update_from_monitor_payload(self, order_id: int | None, client_order_id: str, payload: dict[str, object]) -> LiveOrderRecord:
        record = self.store.update(order_id, client_order_id, payload)
        self._publish_for_state(record)
        self._sync_side_effects(record)
        return record

    def dashboard_snapshot(self) -> dict[str, object]:
        return self.store.dashboard_snapshot()

    def _publish_for_state(self, record: LiveOrderRecord, *, created: bool = False) -> None:
        if created and record.status == OrderState.NEW:
            self.bus.publish(OrderCreated(record))
            return
        event_map = {
            OrderState.NEW: OrderCreated,
            OrderState.PARTIALLY_FILLED: OrderPartiallyFilled,
            OrderState.FILLED: OrderFilled,
            OrderState.CANCELED: OrderCanceled,
            OrderState.REJECTED: OrderRejected,
            OrderState.EXPIRED: OrderExpired,
        }
        self.bus.publish(event_map[record.status](record))

    def _sync_side_effects(self, record: LiveOrderRecord) -> None:
        if record.status == OrderState.PARTIALLY_FILLED:
            return
        if record.status != OrderState.FILLED:
            return
        key = f"{record.order_id}:{record.client_order_id}"
        if key in self._synced_filled_orders:
            return
        self._synced_filled_orders.add(key)
        if self.portfolio is not None and hasattr(self.portfolio, "open_position"):
            self.portfolio.open_position(record.symbol, record.filled_qty, record.average_price, 0.0, record.update_time)
        if self.journal is not None:
            self.journal.add(
                TradeJournalEntry(
                    source="live_order_filled",
                    symbol=record.symbol,
                    side="BUY",
                    quantity=record.filled_qty,
                    entry_time=record.create_time,
                    exit_time="",
                    entry_price=record.average_price,
                    exit_price=0.0,
                    gross_pnl=0.0,
                    fees=0.0,
                    net_pnl=0.0,
                    return_percent=0.0,
                    pair=record.symbol,
                    meta={"order": record.to_dict()},
                )
            )