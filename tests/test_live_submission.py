from __future__ import annotations

from app.live import BinanceOrderSubmissionEngine, LiveConfig, OrderSubmissionResult


PAYLOAD = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quoteOrderQty": 100}


class MockConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def private_post(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append((path, params))
        return {
            "symbol": "BTCUSDT",
            "orderId": 123,
            "clientOrderId": "abc",
            "transactTime": 456,
            "price": "0.00000000",
            "origQty": "0.00100000",
            "executedQty": "0.00000000",
            "status": "NEW",
        }


def test_submission_blocked_when_enabled_false() -> None:
    connector = MockConnector()
    result = BinanceOrderSubmissionEngine(LiveConfig(enabled=False, dry_run=False, confirm_live=True), connector=connector).submit_order(PAYLOAD)

    assert result.success is False
    assert result.raw["reason"] == "live_safety_enabled_false"
    assert connector.calls == []


def test_submission_blocked_when_dry_run_true() -> None:
    connector = MockConnector()
    result = BinanceOrderSubmissionEngine(LiveConfig(enabled=True, dry_run=True, confirm_live=True), connector=connector).submit_order(PAYLOAD)

    assert result.success is False
    assert result.raw["reason"] == "live_safety_dry_run_true"
    assert connector.calls == []


def test_submission_blocked_when_confirm_false() -> None:
    connector = MockConnector()
    result = BinanceOrderSubmissionEngine(LiveConfig(enabled=True, dry_run=False, confirm_live=False), connector=connector).submit_order(PAYLOAD)

    assert result.success is False
    assert result.raw["reason"] == "live_safety_confirm_live_false"
    assert connector.calls == []


def test_submission_allowed_with_mock_connector() -> None:
    connector = MockConnector()
    config = LiveConfig(enabled=True, dry_run=False, confirm_live=True)
    result = BinanceOrderSubmissionEngine(config, connector=connector, operator="tester").submit_order(PAYLOAD)

    assert result.success is True
    assert connector.calls == [("/api/v3/order", PAYLOAD)]


def test_order_response_parsed() -> None:
    result = OrderSubmissionResult.from_binance(
        {
            "symbol": "ETHUSDT",
            "orderId": 99,
            "clientOrderId": "cid",
            "transactTime": 123456,
            "price": "2500.5",
            "origQty": "0.2",
            "executedQty": "0.1",
            "status": "PARTIALLY_FILLED",
        }
    )

    assert result.success is True
    assert result.order_id == 99
    assert result.client_order_id == "cid"
    assert result.symbol == "ETHUSDT"
    assert result.status == "PARTIALLY_FILLED"
    assert result.executed_qty == 0.1
    assert result.orig_qty == 0.2
    assert result.price == 2500.5
    assert result.transact_time == 123456