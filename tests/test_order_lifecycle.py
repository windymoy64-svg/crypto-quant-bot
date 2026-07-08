from __future__ import annotations

from app.analytics.journal import TradeJournal
from app.events.bus import EventBus
from app.live import (
    LiveOrderLifecycleManager,
    OrderCanceled,
    OrderCreated,
    OrderFilled,
    OrderPartiallyFilled,
    OrderRejected,
    OrderState,
    OrderStore,
    OrderSubmissionResult,
)


def _result(status: str = "NEW", executed: float = 0.0, orig: float = 1.0) -> OrderSubmissionResult:
    return OrderSubmissionResult(
        success=True,
        order_id=123,
        client_order_id="cid-123",
        symbol="BTCUSDT",
        status=status,
        executed_qty=executed,
        orig_qty=orig,
        price=100.0,
        transact_time=456,
        raw={"status": status},
    )


def _payload(status: str, executed: str = "0", orig: str = "1", price: str = "100") -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "status": status,
        "executedQty": executed,
        "origQty": orig,
        "price": price,
    }


class PortfolioSpy:
    def __init__(self) -> None:
        self.opened: list[tuple[str, float, float, float, str]] = []

    def open_position(self, symbol: str, quantity: float, price: float, fee: float, timestamp: str) -> None:
        self.opened.append((symbol, quantity, price, fee, timestamp))


def test_order_lifecycle_new_state_publishes_created() -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe("*", events.append)

    record = LiveOrderLifecycleManager(OrderStore(), bus=bus).on_submission(_result("NEW"))

    assert record.status == OrderState.NEW
    assert record.remaining_qty == 1.0
    assert isinstance(events[-1], OrderCreated)


def test_order_lifecycle_partially_filled_updates_qty() -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe("*", events.append)
    manager = LiveOrderLifecycleManager(OrderStore(), bus=bus)
    manager.on_submission(_result("NEW"))

    record = manager.update_from_monitor_payload(123, "cid-123", _payload("PARTIALLY_FILLED", executed="0.4", orig="1"))

    assert record.status == OrderState.PARTIALLY_FILLED
    assert record.filled_qty == 0.4
    assert record.remaining_qty == 0.6
    assert isinstance(events[-1], OrderPartiallyFilled)


def test_order_lifecycle_filled_updates_portfolio_and_journal() -> None:
    portfolio = PortfolioSpy()
    journal = TradeJournal()
    bus = EventBus()
    events: list[object] = []
    bus.subscribe("*", events.append)
    manager = LiveOrderLifecycleManager(OrderStore(), bus=bus, portfolio=portfolio, journal=journal)
    manager.on_submission(_result("NEW"))

    record = manager.update_from_monitor_payload(123, "cid-123", _payload("FILLED", executed="1", orig="1", price="101"))

    assert record.status == OrderState.FILLED
    assert portfolio.opened and portfolio.opened[0][0] == "BTCUSDT"
    assert journal.entries and journal.entries[0].source == "live_order_filled"
    assert isinstance(events[-1], OrderFilled)


def test_order_lifecycle_rejected_state() -> None:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe("*", events.append)

    record = LiveOrderLifecycleManager(OrderStore(), bus=bus).on_submission(_result("REJECTED"))

    assert record.status == OrderState.REJECTED
    assert isinstance(events[-1], OrderRejected)


def test_order_lifecycle_canceled_does_not_open_position() -> None:
    portfolio = PortfolioSpy()
    bus = EventBus()
    events: list[object] = []
    bus.subscribe("*", events.append)
    manager = LiveOrderLifecycleManager(OrderStore(), bus=bus, portfolio=portfolio)
    manager.on_submission(_result("NEW"))

    record = manager.update_from_monitor_payload(123, "cid-123", _payload("CANCELED", executed="0", orig="1"))

    assert record.status == OrderState.CANCELED
    assert portfolio.opened == []
    assert isinstance(events[-1], OrderCanceled)
    assert manager.dashboard_snapshot()["order_history"]