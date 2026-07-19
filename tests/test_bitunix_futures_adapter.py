"""Tests for the Bitunix Futures adapter used by the Executor Agent."""

from __future__ import annotations

from typing import Any

from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.bitunix_futures_adapter import (
    BitunixCredentials,
    BitunixFuturesExecutorAdapter,
    BitunixLiveSafetyGate,
    _map_status,
)
from app.executor_agent.models import OrderRequest
from app.decision_agent.models import Decision, EntryPlan


def _open_gate() -> BitunixLiveSafetyGate:
    return BitunixLiveSafetyGate(enabled=True, dry_run=False, confirm_live=True)


def _capturing_transport(response: dict[str, Any]) -> Any:
    calls: list[dict[str, Any]] = []

    def _transport(*, url: str, headers: dict[str, str], body: dict[str, Any]):
        calls.append({"url": url, "headers": headers, "body": body})
        return response

    _transport.calls = calls  # type: ignore[attr-defined]
    return _transport


def _adapter(
    *,
    response: dict[str, Any] | None = None,
    gate: BitunixLiveSafetyGate | None = None,
    credentials: BitunixCredentials | None = None,
) -> tuple[BitunixFuturesExecutorAdapter, Any]:
    transport = _capturing_transport(response or {"code": 0, "data": {}})
    adapter = BitunixFuturesExecutorAdapter(
        credentials or BitunixCredentials("key", "secret"),
        safety_gate=gate or _open_gate(),
        transport=transport,
    )
    return adapter, transport


def test_safety_gate_blocks_dry_run() -> None:
    adapter, transport = _adapter(
        gate=BitunixLiveSafetyGate(enabled=True, dry_run=True, confirm_live=True),
    )
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert result.reason == "safety_gate_dry_run"
    assert transport.calls == []


def test_safety_gate_blocks_disabled() -> None:
    adapter, transport = _adapter(
        gate=BitunixLiveSafetyGate(enabled=False, dry_run=False, confirm_live=True),
    )
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert result.reason == "safety_gate_disabled"
    assert transport.calls == []


def test_safety_gate_blocks_confirm_missing() -> None:
    adapter, _ = _adapter(
        gate=BitunixLiveSafetyGate(enabled=True, dry_run=False, confirm_live=False),
    )
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert result.reason == "safety_gate_confirm_required"


def test_missing_credentials_rejected() -> None:
    adapter, _ = _adapter(credentials=BitunixCredentials("", ""))
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert result.reason == "credentials_missing"


def test_market_order_translated_correctly() -> None:
    adapter, transport = _adapter(response={
        "code": 0,
        "data": {"orderId": "abc123", "dealVolume": "0.5", "dealAvgPrice": "100.5"},
    })
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    call = transport.calls[0]
    assert call["body"]["symbol"] == "BTCUSDT"
    assert call["body"]["side"] == "BUY"
    assert call["body"]["orderType"] == "MARKET"
    assert call["body"]["tradeSide"] == "OPEN"
    assert call["body"]["reduceOnly"] is False
    assert "price" not in call["body"]
    assert result.order_id == "abc123"
    assert result.filled_quantity == 0.5
    assert result.average_price == 100.5


def test_limit_order_has_price_and_gtc() -> None:
    adapter, transport = _adapter(response={
        "code": 0, "data": {"orderId": "xyz", "status": "NEW"},
    })
    order = OrderRequest(
        symbol="ETH/USDT", side="SELL", order_type="LIMIT",
        quantity=2.0, price=3200.0, reduce_only=True,
        meta={"position_id": "position-eth"},
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    call = transport.calls[0]
    assert call["body"]["orderType"] == "LIMIT"
    assert call["body"]["price"] == "3200"
    assert call["body"]["effect"] == "GTC"
    assert call["body"]["tradeSide"] == "CLOSE"
    assert result.status == "SUBMITTED"


def test_reduce_only_without_position_id_rejected_before_network() -> None:
    adapter, transport = _adapter()
    order = OrderRequest(
        symbol="ETH/USDT", side="SELL", order_type="LIMIT",
        quantity=2.0, price=3200.0, reduce_only=True,
    )

    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")

    assert result.status == "REJECTED"
    assert "position_id_required_for_close" in result.reason
    assert transport.calls == []


def test_stop_order_rejected_by_adapter() -> None:
    adapter, transport = _adapter()
    order = OrderRequest(
        symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET",
        quantity=0.5, stop_price=95.0, reduce_only=True,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert "order_type_not_supported" in result.reason
    assert transport.calls == []


def test_error_code_from_exchange_becomes_rejected() -> None:
    adapter, _ = _adapter(response={"code": 10001, "msg": "insufficient balance"})
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.5,
    )
    result = adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    assert result.status == "REJECTED"
    assert "insufficient balance" in result.reason


def test_headers_include_signed_fields() -> None:
    adapter, transport = _adapter(response={"code": 0, "data": {"orderId": "1"}})
    order = OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="MARKET", quantity=0.1,
    )
    adapter.place_order(order, timestamp="2024-01-01T00:00:00Z")
    headers = transport.calls[0]["headers"]

    assert headers["api-key"] == "key"
    assert len(headers["sign"]) == 64  # sha256 hex
    assert headers["nonce"]
    assert headers["timestamp"]
    assert headers["User-Agent"].startswith("crypto-quant-bot/1.0")


def test_map_status_variants() -> None:
    assert _map_status(status="FILLED", filled=1, requested=1) == "FILLED"
    assert _map_status(status="PART_FILLED", filled=0.3, requested=1) == "PARTIAL"
    assert _map_status(status="NEW", filled=0, requested=1) == "SUBMITTED"
    assert _map_status(status="CANCELLED", filled=0, requested=1) == "CANCELLED"
    assert _map_status(status="", filled=0.4, requested=1) == "PARTIAL"
    assert _map_status(status="", filled=0, requested=1) == "SUBMITTED"


def test_executor_agent_uses_bitunix_adapter_when_live() -> None:
    adapter, transport = _adapter(response={
        "code": 0, "data": {"orderId": "1", "dealVolume": "0.5", "dealAvgPrice": "100"},
    })
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
    assert transport.calls  # adapter was called for at least entry


def test_live_entry_attaches_stop_and_take_profit_in_single_request() -> None:
    adapter, transport = _adapter(response={
        "code": 0, "data": {"orderId": "protected-1", "status": "NEW"},
    })
    executor = ExecutorAgent(live=True, exchange_adapter=adapter)

    report = executor.execute(Decision(
        action="ENTRY_BUY", symbol="BTC/USDT", confidence="HIGH",
        confidence_score=90.0, reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY", entry_price=100.0, stop_loss=97.0,
            take_profit_1=106.0, take_profit_2=109.0,
            risk_reward=2.0,
        ),
        regime="TRENDING_BULLISH", confluence_score=80.0,
        timestamp="2024-01-01T00:00:00Z",
    ))

    assert len(transport.calls) == 1
    body = transport.calls[0]["body"]
    assert body["slPrice"] == "97"
    assert body["slOrderType"] == "MARKET"
    assert body["tpPrice"] == "106"
    assert body["tpOrderType"] == "MARKET"
    assert report.results[0].order_id == "protected-1"
    assert all(result.status != "REJECTED" for result in report.results)


def test_plan_rejects_before_network_when_protective_stop_missing() -> None:
    adapter, transport = _adapter()
    orders = [OrderRequest(
        symbol="BTC/USDT", side="BUY", order_type="LIMIT", quantity=0.1,
        price=100.0, meta={"role": "entry"},
    )]

    results = adapter.place_orders(orders, timestamp="2024-01-01T00:00:00Z")

    assert transport.calls == []
    assert results[0].status == "REJECTED"
    assert results[0].reason == "protective_stop_required_before_live_entry"


def test_plan_dry_run_never_calls_network() -> None:
    adapter, transport = _adapter(
        gate=BitunixLiveSafetyGate(enabled=True, dry_run=True, confirm_live=True),
    )
    orders = [
        OrderRequest(symbol="BTC/USDT", side="BUY", order_type="LIMIT",
                     quantity=0.1, price=100.0, meta={"role": "entry"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET",
                     quantity=0.1, stop_price=97.0, reduce_only=True,
                     meta={"role": "stop_loss"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.1, price=106.0, reduce_only=True,
                     meta={"role": "take_profit_1"}),
    ]

    results = adapter.place_orders(orders, timestamp="2024-01-01T00:00:00Z")

    assert transport.calls == []
    assert all(result.reason == "safety_gate_dry_run" for result in results)
