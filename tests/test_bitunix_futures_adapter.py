"""Tests for the Bitunix Futures adapter used by the Executor Agent."""

from __future__ import annotations

import json
from typing import Any

import pytest

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
    executor = ExecutorAgent(
        live=True, exchange_adapter=adapter, paper_parity_verified=True,
    )

    decision = Decision(
        action="ENTRY_BUY", symbol="BTC/USDT",
        confidence="HIGH", confidence_score=90.0, reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY", entry_price=100.0, stop_loss=97.0,
            take_profit_1=106.0, take_profit_2=109.0,
            take_profit_3=112.0, risk_reward=2.0,
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
    executor = ExecutorAgent(
        live=True, exchange_adapter=adapter, paper_parity_verified=True,
    )

    report = executor.execute(Decision(
        action="ENTRY_BUY", symbol="BTC/USDT", confidence="HIGH",
        confidence_score=90.0, reasons=["test"],
        entry_plan=EntryPlan(
            side="BUY", entry_price=100.0, stop_loss=97.0,
            take_profit_1=106.0, take_profit_2=109.0,
            take_profit_3=112.0,
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
    assert [result.status for result in report.results[2:]] == [
        "PENDING", "PENDING", "PENDING",
    ]


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
    assert by_role["take_profit_2"].reason == "queued_until_position_id_available"
    assert by_role["take_profit_3"].reason == "queued_until_position_id_available"

    reconciled = adapter.reconcile_take_profits([{
        "position_id": "position-1", "symbol": "BTCUSDT", "side": "BUY",
        "entry_price": 100.0, "quantity": 1.0, "stop_loss": 97.0,
    }], timestamp="2026-01-01T00:01:00Z")

    assert len(reconciled) == 3
    tp_calls = transport.calls[1:]
    assert all(call["url"].endswith("/tpsl/place_order") for call in tp_calls)
    assert [call["body"]["tpPrice"] for call in tp_calls] == ["106", "109", "112"]
    assert [call["body"]["tpQty"] for call in tp_calls] == ["0.3", "0.3", "0.4"]
    assert all(call["body"]["positionId"] == "position-1" for call in tp_calls)
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == []


def test_expired_tp_queue_requires_manual_action_without_closing(tmp_path) -> None:
    calls = []

    def transport(*, url, headers, body):
        calls.append({"url": url, "body": body})
        return {"code": 0, "data": {"orderId": "unexpected", "status": "NEW"}}

    pending_path = tmp_path / "pending-tp.json"
    pending_path.write_text(json.dumps({"plans": [{
        "entry_order_id": "entry-1", "symbol": "KAITOUSDT",
        "position_side": "LONG", "strategy": "paper_live_lifecycle_v1",
        "created_at": "2020-01-01T00:00:00+00:00",
        "take_profits": [{
            "role": "take_profit_1", "side": "SELL", "quantity": 1.0,
            "price": 1.04,
        }],
    }]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([{
        "position_id": "position-1", "symbol": "KAITOUSDT", "side": "BUY",
        "quantity": 1.0, "entry_price": 1.0, "stop_loss": 0.98,
    }], timestamp="2026-01-01T00:01:00+00:00")

    assert results == []
    assert calls == []
    saved = json.loads(pending_path.read_text(encoding="utf-8"))["plans"][0]
    assert saved["protection_status"] == "manual_action_required"
    assert "KAITO/USDT" in adapter._blocked_entry_symbols


def test_reconcile_preserves_legacy_ladder_without_submitting_it(tmp_path) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "tp"}})
    pending_path = tmp_path / "pending-tp.json"
    legacy = {
        "entry_order_id": "old-entry", "symbol": "BNB/USDT",
        "position_side": "LONG",
        "take_profits": [
            {"role": "take_profit_1", "side": "SELL", "quantity": 0.1, "price": 600},
            {"role": "take_profit_2", "side": "SELL", "quantity": 0.1, "price": 610},
        ],
    }
    pending_path.write_text(json.dumps({"plans": [legacy]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([{
        "position_id": "current-position", "symbol": "BNBUSDT", "side": "BUY",
    }], timestamp="2026-01-01T00:01:00Z")

    assert results == []
    assert transport.calls == []
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == [legacy]


def test_live_exit_persists_bot_reason_by_exchange_order_id(tmp_path) -> None:
    metadata_path = tmp_path / "order-metadata.json"
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=_capturing_transport({"code": 0, "data": {"orderId": "exit-123"}}),
        pending_tp_path=tmp_path / "pending-tp.json",
        order_metadata_path=metadata_path,
    )
    order = OrderRequest(
        symbol="BTC/USDT", side="SELL", order_type="MARKET", quantity=0.1,
        reduce_only=True,
        meta={
            "role": "exit", "reason": "choch_bearish_against_long",
            "position_id": "position-1",
        },
    )

    result = adapter.place_order(order, timestamp="2026-01-01T00:00:00Z")

    assert result.order_id == "exit-123"
    saved = json.loads(metadata_path.read_text(encoding="utf-8"))["orders"]["exit-123"]
    assert saved["reason"] == "choch_bearish_against_long"
    assert saved["role"] == "exit"
    assert saved["position_id"] == "position-1"


def test_metadata_write_failure_never_changes_accepted_exchange_order(
    tmp_path, monkeypatch,
) -> None:
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=_capturing_transport({"code": 0, "data": {"orderId": "accepted-1"}}),
        order_metadata_path=tmp_path / "order-metadata.json",
    )
    monkeypatch.setattr(
        adapter, "_record_order_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk busy")),
    )

    result = adapter.place_order(
        OrderRequest(
            symbol="BTC/USDT", side="SELL", order_type="MARKET", quantity=0.1,
            reduce_only=True,
            meta={"role": "exit", "reason": "stop_loss", "position_id": "p1"},
        ),
        timestamp="2026-01-01T00:00:00Z",
    )

    assert result.order_id == "accepted-1"
    assert result.status == "SUBMITTED"


def test_tp1_reconcile_does_not_duplicate_accepted_order(tmp_path) -> None:
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
    position = [{
        "position_id": "p-2", "symbol": "BTCUSDT", "side": "LONG",
        "entry_price": 100.0, "quantity": 1.0, "stop_loss": 97.0,
    }]

    first = adapter.reconcile_take_profits(position, timestamp="2026-01-01T00:01:00Z")
    second = adapter.reconcile_take_profits(position, timestamp="2026-01-01T00:02:00Z")

    assert [result.status for result in first] == ["SUBMITTED", "REJECTED"]
    assert [result.status for result in second] == ["SUBMITTED", "SUBMITTED"]
    tp_prices = [call["body"].get("tpPrice") for call in calls if "/tpsl/" in call["url"]]
    # Accepted TP1 is not duplicated; retry starts from rejected TP2.
    assert tp_prices == ["106", "109", "109", "112"]


def test_reconcile_submits_only_newest_matching_tp_plan(tmp_path) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "tp-latest"}})
    pending_path = tmp_path / "pending-tp.json"
    plans = [{
        "entry_order_id": order_id,
        "symbol": "SUI/USDT",
        "position_side": "SHORT",
        "strategy": "tp1_partial_trailing_v1",
        "take_profits": [{
            "role": "take_profit_1", "side": "BUY",
            "quantity": quantity, "price": 0.678525,
        }],
    } for order_id, quantity in (("older", 4.48), ("latest", 4.23))]
    pending_path.write_text(json.dumps({"plans": plans}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([{
        "position_id": "sui-position", "symbol": "SUIUSDT", "side": "SELL",
        "quantity": 21.4,
    }], timestamp="2026-07-31T15:10:00Z")

    assert [result.status for result in results] == ["SUBMITTED"]
    assert len(transport.calls) == 1
    assert transport.calls[0]["body"]["positionId"] == "sui-position"
    assert transport.calls[0]["body"]["tpQty"] == "4.23"
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == []


def test_reconcile_prunes_queue_when_position_already_has_tp(tmp_path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def transport(*, url, headers, body):
        calls.append({"url": url, "headers": headers, "body": body})
        if url.endswith("/tpsl/get_pending_orders"):
            return {"code": 0, "data": [{
                "positionId": "p1", "symbol": "SUIUSDT",
                "tpPrice": "0.6785", "tpQty": "4.2",
            }]}
        return {"code": 0, "data": {"orderId": "unexpected"}}

    pending_path = tmp_path / "pending-tp.json"
    pending_path.write_text(json.dumps({"plans": [{
        "entry_order_id": "stale", "symbol": "SUI/USDT",
        "position_side": "SHORT", "strategy": "tp1_partial_trailing_v1",
        "take_profits": [{
            "role": "take_profit_1", "side": "BUY",
            "quantity": 4.2, "price": 0.678525,
        }],
    }]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )
    monkeypatch.setattr(adapter, "pending_tpsl", lambda **_: [{
        "positionId": "p1", "symbol": "SUIUSDT",
        "tpPrice": "0.6785", "tpQty": "4.2",
    }])

    results = adapter.reconcile_take_profits([{
        "position_id": "p1", "symbol": "SUIUSDT", "side": "SELL",
        "take_profit": "0.6785",
    }], timestamp="2026-07-31T15:15:00Z")

    assert results == []
    assert calls == []
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == []


def test_repair_unprotected_position_places_default_three_level_ladder(tmp_path, monkeypatch) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "repair-tp"}})
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=tmp_path / "pending-tp.json",
    )
    monkeypatch.setattr(adapter, "pending_tpsl", lambda **_: [])

    results = adapter.repair_unprotected_positions([{
        "position_id": "ada-position", "symbol": "ADAUSDT", "side": "SELL",
        "entry_price": "0.1942", "stop_loss": "0.1997", "quantity": 51.0,
    }], timestamp="2026-08-10T00:00:00Z")

    assert len(results) == 3
    assert all(result.status == "SUBMITTED" for result in results)
    assert [call["body"]["tpPrice"] for call in transport.calls] == [
        "0.1832", "0.1777", "0.1722",
    ]
    assert [call["body"]["tpQty"] for call in transport.calls] == [
        "15.3", "15.3", "20.4",
    ]


def test_repair_skips_existing_tp_even_when_position_aggregate_is_null(
    tmp_path, monkeypatch,
) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "unexpected"}})
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=tmp_path / "pending-tp.json",
    )
    monkeypatch.setattr(adapter, "pending_tpsl", lambda **_: [{
        "position_id": "ada-position", "symbol": "ADAUSDT",
        "tpPrice": "0.1832", "tpQty": "15.3",
    }])

    results = adapter.repair_unprotected_positions([{
        "position_id": "ada-position", "symbol": "ADAUSDT", "side": "SELL",
        "entry_price": "0.1942", "stop_loss": "0.1997", "quantity": 51.0,
        "take_profit": None,
    }], timestamp="2026-08-10T00:00:00Z")

    assert results == []
    assert transport.calls == []


def test_reconcile_does_not_prune_stale_position_tp_without_pending_tpsl(
    tmp_path, monkeypatch,
) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "tp-1"}})
    pending_path = tmp_path / "pending-tp.json"
    pending_path.write_text(json.dumps({"plans": [{
        "entry_order_id": "stale-row", "symbol": "SUI/USDT",
        "position_side": "SHORT", "strategy": "tp1_partial_trailing_v1",
        "take_profits": [{
            "role": "take_profit_1", "side": "BUY",
            "quantity": 4.2, "price": 0.678525,
        }],
    }]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )
    monkeypatch.setattr(adapter, "pending_tpsl", lambda **_: [])

    results = adapter.reconcile_take_profits([{
        "position_id": "p1", "symbol": "SUIUSDT", "side": "SELL",
        "take_profit": "0.6785",
    }], timestamp="2026-07-31T15:16:00Z")

    assert [result.status for result in results] == ["SUBMITTED"]
    assert transport.calls[0]["url"].endswith("/tpsl/place_order")


def test_reconcile_preserves_plan_when_position_id_is_missing(tmp_path, caplog) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "unexpected"}})
    pending_path = tmp_path / "pending-tp.json"
    plan = {
        "entry_order_id": "missing-id", "symbol": "BNB/USDT",
        "position_side": "LONG", "strategy": "tp1_partial_trailing_v1",
        "take_profits": [{
            "role": "take_profit_1", "side": "SELL",
            "quantity": 0.1, "price": 600,
        }],
    }
    pending_path.write_text(json.dumps({"plans": [plan]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([{
        "symbol": "BNBUSDT", "side": "BUY",
    }], timestamp="2026-07-31T15:17:00Z")

    assert results == []
    assert transport.calls == []
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == [plan]
    assert "reason=position_id_missing" in caplog.text


def test_reconcile_prunes_old_orphan_plan_without_touching_exchange(tmp_path) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "unexpected"}})
    pending_path = tmp_path / "pending-tp.json"
    pending_path.write_text(json.dumps({"plans": [{
        "entry_order_id": "orphan", "symbol": "SOL/USDT",
        "position_side": "SHORT", "strategy": "tp1_partial_trailing_v1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "take_profits": [{
            "role": "take_profit_1", "side": "BUY", "quantity": 1.0,
            "price": 100,
        }],
    }]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([], timestamp="2026-01-01T02:00:00+00:00")

    assert results == []
    assert transport.calls == []
    assert json.loads(pending_path.read_text(encoding="utf-8"))["plans"] == []


def test_reconcile_recomputes_rr_tp_from_exchange_entry_and_stop(tmp_path) -> None:
    transport = _capturing_transport({"code": 0, "data": {"orderId": "tp-rr2"}})
    pending_path = tmp_path / "pending-tp.json"
    pending_path.write_text(json.dumps({"plans": [{
        "entry_order_id": "entry", "symbol": "SUI/USDT",
        "position_side": "SHORT", "strategy": "tp1_partial_trailing_v1",
        "take_profits": [{
            "role": "take_profit_1", "side": "BUY", "quantity": 4.2,
            "price": 0.678525, "target_risk_reward": 2.0,
        }],
    }]}), encoding="utf-8")
    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=transport, pending_tp_path=pending_path,
    )

    results = adapter.reconcile_take_profits([{
        "position_id": "p1", "symbol": "SUIUSDT", "side": "SELL",
        "entry_price": "0.6847", "stop_loss": "0.6926", "take_profit": None,
    }], timestamp="2026-07-31T15:20:00Z")

    assert results[0].meta["tp_level_source"] == "configured_rr_exchange_fill"
    assert transport.calls[0]["body"]["tpPrice"] == "0.6689"


def test_tighten_stop_modifies_in_place_and_verifies_exchange_state(tmp_path) -> None:
    rows = [{
        "id": "sl-1", "positionId": "p1", "symbol": "BTCUSDT",
        "slPrice": "97", "slQty": "1", "tpPrice": None,
    }]

    def post(*, url, headers, body):
        assert url.endswith("/api/v1/futures/tpsl/modify_order")
        rows[0]["slPrice"] = body["slPrice"]
        rows[0]["slQty"] = body["slQty"]
        return {"code": 0, "data": {"orderId": "sl-1"}}

    def query(*, url, headers, params):
        return {"code": 0, "data": list(rows)}

    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=post, query_transport=query,
        pending_tp_path=tmp_path / "pending.json",
    )

    updated = adapter.tighten_stop(
        symbol="BTC/USDT", position_id="p1", side="LONG",
        new_stop=100, quantity=0.7,
    )
    assert updated["slPrice"] == "100"
    assert updated["slQty"] == "0.7"


def test_tighten_stop_rejects_widening_without_post(tmp_path) -> None:
    posts = []

    def query(**kwargs):
        return {"code": 0, "data": [{
            "id": "sl-1", "positionId": "p1", "symbol": "BTCUSDT",
            "slPrice": "97", "slQty": "1",
        }]}

    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=lambda **kwargs: posts.append(kwargs), query_transport=query,
        pending_tp_path=tmp_path / "pending.json",
    )
    with pytest.raises(ValueError, match="tighten"):
        adapter.tighten_stop(
            symbol="BTC/USDT", position_id="p1", side="LONG",
            new_stop=96, quantity=1,
        )
    assert posts == []


def test_cancel_tpsl_requires_post_state_confirmation(tmp_path) -> None:
    rows = [{"id": "tp-1", "positionId": "p1", "symbol": "BTCUSDT", "tpPrice": "106"}]

    def post(*, url, headers, body):
        rows.clear()
        return {"code": 0, "data": {"orderId": body["orderId"]}}

    def query(**kwargs):
        return {"code": 0, "data": list(rows)}

    adapter = BitunixFuturesExecutorAdapter(
        BitunixCredentials("key", "secret"), safety_gate=_open_gate(),
        transport=post, query_transport=query,
        pending_tp_path=tmp_path / "pending.json",
    )
    assert adapter.cancel_tpsl_order(symbol="BTC/USDT", order_id="tp-1") is True
