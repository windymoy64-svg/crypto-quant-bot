"""Tests for the Bitunix Futures adapter used by the Executor Agent."""

from __future__ import annotations

import json
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


def test_openapi_unsupported_pair_is_persisted(
    tmp_path, monkeypatch,
) -> None:
    from app.executor_agent import bitunix_futures_adapter as module

    path = tmp_path / "unsupported.json"
    monkeypatch.setattr(module, "BITUNIX_OPENAPI_BLOCKLIST_PATH", path)
    adapter, _ = _adapter(response={
        "code": 710002,
        "msg": "This trading pair does not currently support trading via OpenAPI.",
    })
    order = OrderRequest(
        symbol="TSLA/USDT", side="BUY", order_type="LIMIT",
        quantity=0.01, price=300.0,
    )

    result = adapter.place_order(order, timestamp="2026-07-31T00:00:00Z")

    assert result.status == "REJECTED"
    assert path.exists()
    assert "TSLA/USDT" in path.read_text(encoding="utf-8")


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


def test_live_entry_attaches_stop_and_queues_take_profit(tmp_path) -> None:
    transport = _capturing_transport({
        "code": 0, "data": {"orderId": "protected-1", "status": "NEW"},
    })
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=tmp_path / "pending-tp.json",
    )
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
    assert body["orderType"] == "MARKET"
    assert "price" not in body
    assert body["slPrice"] == "97"
    assert body["slOrderType"] == "MARKET"
    assert "tpPrice" not in body
    assert report.results[0].order_id == "protected-1"
    assert all(result.status != "REJECTED" for result in report.results)
    assert [result.status for result in report.results[2:]] == ["PENDING", "PENDING"]


def test_configured_leverage_is_applied_before_live_entry() -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "1"}})
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, leverage=25,
    )
    orders = [
        OrderRequest(symbol="BTC/USDT", side="BUY", order_type="LIMIT", quantity=0.1, price=100, meta={"role":"entry"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET", quantity=0.1, stop_price=97, reduce_only=True, meta={"role":"stop_loss"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT", quantity=0.1, price=106, reduce_only=True, meta={"role":"take_profit_1"}),
    ]

    adapter.place_orders(orders, timestamp="2026-01-01T00:00:00Z")

    assert transport.calls[0]["url"].endswith("/account/change_leverage")
    assert transport.calls[0]["body"]["leverage"] == 25
    assert transport.calls[1]["url"].endswith("/trade/place_order")


def test_leverage_failure_blocks_entry_order() -> None:
    calls = []
    def transport(*, url, headers, body):
        calls.append({"url":url,"body":body})
        return {"code": 1, "msg": "leverage rejected"}
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, leverage=25,
    )
    orders = [
        OrderRequest(symbol="BTC/USDT", side="BUY", order_type="LIMIT", quantity=0.1, price=100, meta={"role":"entry"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET", quantity=0.1, stop_price=97, reduce_only=True, meta={"role":"stop_loss"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT", quantity=0.1, price=106, reduce_only=True, meta={"role":"take_profit_1"}),
    ]

    results = adapter.place_orders(orders, timestamp="2026-01-01T00:00:00Z")

    assert len(calls) == 1
    assert all(result.status == "REJECTED" for result in results)
    assert all("change_leverage_failed" in result.reason for result in results)


def test_compact_pending_symbol_blocks_duplicate_before_network() -> None:
    adapter, transport = _adapter()
    adapter._blocked_entry_symbols = {"LINK/USDT"}
    orders = [
        OrderRequest(symbol="LINKUSDT", side="SELL", order_type="LIMIT", quantity=1, price=8.4, meta={"role":"entry"}),
        OrderRequest(symbol="LINKUSDT", side="BUY", order_type="STOP_MARKET", quantity=1, stop_price=8.5, reduce_only=True, meta={"role":"stop_loss"}),
        OrderRequest(symbol="LINKUSDT", side="BUY", order_type="LIMIT", quantity=1, price=8.2, reduce_only=True, meta={"role":"take_profit_1"}),
    ]

    results = adapter.place_orders(orders, timestamp="2026-01-01T00:00:00Z")

    assert transport.calls == []
    assert all(result.reason == "pending_entry_exists" for result in results)


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


def test_plan_reconciles_tp1_tp2_tp3_through_official_tpsl_endpoint(tmp_path) -> None:
    transport = _capturing_transport({
        "code": 0, "data": {"orderId": "entry-1"},
    })
    pending_path = tmp_path / "pending-tp.json"
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )
    orders = [
        OrderRequest(symbol="BTC/USDT", side="BUY", order_type="LIMIT",
                     quantity=1.0, price=100.0, meta={"role": "entry"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET",
                     quantity=1.0, stop_price=97.0, reduce_only=True,
                     meta={"role": "stop_loss"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.3, price=106.0, reduce_only=True,
                     meta={"role": "take_profit_1"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.3, price=109.0, reduce_only=True,
                     meta={"role": "take_profit_2"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.4, price=112.0, reduce_only=True,
                     meta={"role": "take_profit_3"}),
    ]

    results = adapter.place_orders(orders, timestamp="2026-01-01T00:00:00Z")

    assert len(transport.calls) == 1
    body = transport.calls[0]["body"]
    assert body["slPrice"] == "97"
    assert "tpPrice" not in body
    by_role = {result.meta["role"]: result for result in results}
    assert by_role["stop_loss"].reason == "attached_to_entry"
    assert by_role["take_profit_1"].status == "PENDING"
    assert by_role["take_profit_2"].status == "PENDING"
    assert by_role["take_profit_3"].status == "PENDING"

    reconciled = adapter.reconcile_take_profits([{
        "position_id": "position-1", "symbol": "BTCUSDT", "side": "BUY",
    }], timestamp="2026-01-01T00:01:00Z")

    assert len(reconciled) == 3
    tp_calls = transport.calls[1:]
    assert all(call["url"].endswith("/tpsl/place_order") for call in tp_calls)
    assert [call["body"]["tpPrice"] for call in tp_calls] == ["106", "109", "112"]
    assert [call["body"]["tpQty"] for call in tp_calls] == ["0.3", "0.3", "0.4"]
    assert all(call["body"]["positionId"] == "position-1" for call in tp_calls)
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == []


def test_tp_reconcile_retry_does_not_duplicate_accepted_levels(tmp_path) -> None:
    calls: list[dict[str, Any]] = []

    def transport(*, url, headers, body):
        calls.append({"url": url, "body": body})
        if url.endswith("/trade/place_order"):
            return {"code": 0, "data": {"orderId": "entry-2"}}
        if body.get("tpPrice") == "109" and sum(
            1 for call in calls if call["body"].get("tpPrice") == "109"
        ) == 1:
            return {"code": 1, "msg": "temporary rejection"}
        return {"code": 0, "data": {"orderId": f"tp-{body.get('tpPrice')}"}}

    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=tmp_path / "pending-tp.json",
    )
    orders = [
        OrderRequest(symbol="BTC/USDT", side="BUY", order_type="LIMIT",
                     quantity=1, price=100, meta={"role": "entry"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="STOP_MARKET",
                     quantity=1, stop_price=97, reduce_only=True,
                     meta={"role": "stop_loss"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.3, price=106, reduce_only=True,
                     meta={"role": "take_profit_1"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.3, price=109, reduce_only=True,
                     meta={"role": "take_profit_2"}),
        OrderRequest(symbol="BTC/USDT", side="SELL", order_type="LIMIT",
                     quantity=0.4, price=112, reduce_only=True,
                     meta={"role": "take_profit_3"}),
    ]
    adapter.place_orders(orders, timestamp="2026-01-01T00:00:00Z")
    position = [{"position_id": "p-2", "symbol": "BTCUSDT", "side": "LONG"}]

    first = adapter.reconcile_take_profits(position, timestamp="2026-01-01T00:01:00Z")
    second = adapter.reconcile_take_profits(position, timestamp="2026-01-01T00:02:00Z")

    assert [result.status for result in first] == ["SUBMITTED", "REJECTED"]
    assert [result.status for result in second] == ["SUBMITTED", "SUBMITTED"]
    tp_prices = [call["body"].get("tpPrice") for call in calls if "/tpsl/" in call["url"]]
    assert tp_prices == ["106", "109", "109", "112"]
