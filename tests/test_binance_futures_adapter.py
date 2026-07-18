"""Tests for the Binance Futures adapter used by the Executor Agent."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.exchange.binance_futures.orders import (
    FuturesOrderRequest,
    FuturesOrderResult,
    OrderType as FuturesOrderType,
    PositionSide,
    TimeInForce,
)
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.binance_futures_adapter import (
    BinanceFuturesExecutorAdapter,
    _map_binance_status,
)
from app.executor_agent.models import OrderRequest
from app.decision_agent.models import Decision, EntryPlan


def _accepted_result(
    status: str = "FILLED", executed: float = 1.0, avg: float = 100.0,
) -> FuturesOrderResult:
    return FuturesOrderResult(
        accepted=True, dry_run=False, order_id=12345, client_order_id="abc",
        status=status, executed_qty=executed, avg_price=avg,
        raw_response={"orderId": 12345, "status": status},
    )


def _rejected_result(reason: str = "safety_gate_dry_run") -> FuturesOrderResult:
    return FuturesOrderResult(
        accepted=False, dry_run=True, order_id=None, client_order_id=None,
        status=None, executed_qty=0.0, avg_price=0.0, reason=reason,
    )


def test_adapter_translates_market_buy() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result()
    adapter = BinanceFuturesExecutorAdapter(engine)

    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET",
        quantity=0.5, meta={"role": "entry"},
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    engine.submit_order.assert_called_once()
    submitted = engine.submit_order.call_args.args[0]
    assert isinstance(submitted, FuturesOrderRequest)
    assert submitted.symbol == "BTCUSDT"
    assert submitted.order_type is FuturesOrderType.MARKET
    assert submitted.quantity == 0.5
    assert submitted.time_in_force is None
    assert result.status == "FILLED"
    assert result.order_id == "12345"


def test_adapter_translates_limit_order_with_tif() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result(status="NEW", executed=0.0)
    adapter = BinanceFuturesExecutorAdapter(engine)

    order = OrderRequest(
        symbol="ETH/USDT", side="SELL", order_type="LIMIT",
        quantity=2.0, price=3200.0,
        meta={"role": "take_profit_1"}, reduce_only=True,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    submitted = engine.submit_order.call_args.args[0]
    assert submitted.order_type is FuturesOrderType.LIMIT
    assert submitted.price == 3200.0
    assert submitted.time_in_force is TimeInForce.GTC
    assert submitted.reduce_only is True
    assert result.status == "SUBMITTED"


def test_adapter_translates_stop_market() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result(status="NEW", executed=0.0)
    adapter = BinanceFuturesExecutorAdapter(engine)

    order = OrderRequest(
        symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET",
        quantity=0.5, stop_price=95.0, reduce_only=True,
        meta={"role": "stop_loss"},
    )
    adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    submitted = engine.submit_order.call_args.args[0]
    assert submitted.order_type is FuturesOrderType.STOP_MARKET
    assert submitted.stop_price == 95.0
    assert submitted.time_in_force is None


def test_adapter_maps_safety_gate_rejection() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _rejected_result("safety_gate_dry_run")
    adapter = BinanceFuturesExecutorAdapter(engine)

    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    assert result.status == "REJECTED"
    assert "safety_gate_dry_run" in result.reason
    assert result.filled_quantity == 0.0


def test_adapter_maps_partial_fill() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result(
        status="PARTIALLY_FILLED", executed=0.3, avg=100.5,
    )
    adapter = BinanceFuturesExecutorAdapter(engine)

    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="LIMIT",
        quantity=1.0, price=100.0,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    assert result.status == "PARTIAL"
    assert result.filled_quantity == 0.3
    assert result.average_price == 100.5


def test_adapter_position_side_configurable() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result()
    adapter = BinanceFuturesExecutorAdapter(
        engine, position_side=PositionSide.LONG,
    )

    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    submitted = engine.submit_order.call_args.args[0]
    assert submitted.position_side is PositionSide.LONG


def test_map_binance_status_variants() -> None:
    assert _map_binance_status("FILLED", requested_quantity=1, filled_quantity=1) == "FILLED"
    assert _map_binance_status("PARTIALLY_FILLED", requested_quantity=1, filled_quantity=0.5) == "PARTIAL"
    assert _map_binance_status("NEW", requested_quantity=1, filled_quantity=0) == "SUBMITTED"
    assert _map_binance_status("CANCELED", requested_quantity=1, filled_quantity=0) == "CANCELLED"
    assert _map_binance_status("REJECTED", requested_quantity=1, filled_quantity=0) == "REJECTED"
    # Empty status but partial fill inferred from quantities
    assert _map_binance_status("", requested_quantity=1, filled_quantity=0.4) == "PARTIAL"


def test_executor_agent_uses_adapter_when_live() -> None:
    engine = MagicMock()
    engine.submit_order.return_value = _accepted_result()
    adapter = BinanceFuturesExecutorAdapter(engine)
    executor = ExecutorAgent(live=True, exchange_adapter=adapter)

    decision = Decision(
        action="ENTRY_BUY", symbol="BTC/USDT",
        confidence="HIGH", confidence_score=90.0, reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY", entry_price=100.0, stop_loss=97.0,
            take_profit_1=106.0, risk_reward=2.0,
        ),
        regime="TRENDING_BULLISH", confluence_score=80.0,
        timestamp="2024-01-01T00:00:00Z",
    )
    report = executor.execute(decision)

    assert report.plan.dry_run is False
    # Adapter called once per generated order (entry + SL + TP orders)
    assert engine.submit_order.call_count == len(report.plan.orders)
    assert all(result.is_success for result in report.results)


def test_executor_agent_recovers_when_adapter_raises() -> None:
    class BrokenAdapter:
        def place_order(self, order, *, timestamp):
            raise RuntimeError("boom")

    executor = ExecutorAgent(live=True, exchange_adapter=BrokenAdapter())

    decision = Decision(
        action="ENTRY_BUY", symbol="BTC/USDT",
        confidence="HIGH", confidence_score=90.0, reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY", entry_price=100.0, stop_loss=97.0,
            take_profit_1=106.0, risk_reward=2.0,
        ),
        regime="TRENDING_BULLISH", confluence_score=80.0,
        timestamp="2024-01-01T00:00:00Z",
    )
    report = executor.execute(decision)

    assert report.plan.dry_run is False
    assert all(result.status == "REJECTED" for result in report.results)
    assert all("adapter_error" in result.reason for result in report.results)
