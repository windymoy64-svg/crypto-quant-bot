from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.client import FuturesHttpError, FuturesHttpResponse
from app.exchange.binance_futures.orders import (
    FuturesLiveSafetyGate,
    FuturesOrderRequest,
    FuturesOrderSubmissionEngine,
    OrderSide,
    OrderType,
    PositionSide,
    TimeInForce,
    WorkingType,
)


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_response: FuturesHttpResponse | Exception | None = None

    def post(self, path, params=None, *, signed=True):  # noqa: ARG002
        self.calls.append((path, dict(params or {})))
        response = self.next_response
        self.next_response = None
        if isinstance(response, Exception):
            raise response
        if response is None:
            return FuturesHttpResponse(status_code=200, body={})
        return response

    def get(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("get should not be called")

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("delete should not be called")


def _open_gate() -> FuturesLiveSafetyGate:
    return FuturesLiveSafetyGate(enabled=True, dry_run=False, confirm_live=True)


def test_request_market_order_params() -> None:
    request = FuturesOrderRequest(
        symbol="btcusdt",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
    )

    params = request.to_params()

    assert params["symbol"] == "BTCUSDT"
    assert params["side"] == "BUY"
    assert params["type"] == "MARKET"
    assert params["quantity"] == "0.01"
    assert params["positionSide"] == "BOTH"
    assert "reduceOnly" not in params


def test_request_limit_order_requires_price_and_tif() -> None:
    with pytest.raises(ValueError, match="LIMIT orders require a positive price"):
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
        ).to_params()

    with pytest.raises(ValueError, match="LIMIT orders require time_in_force"):
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
            price=60000,
        ).to_params()


def test_request_close_position_only_valid_for_stop_markets() -> None:
    with pytest.raises(ValueError, match="close_position"):
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            close_position=True,
        ).to_params()


def test_request_close_position_and_reduce_only_mutex() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            close_position=True,
            reduce_only=True,
            stop_price=55000,
        ).to_params()


def test_gate_blocks_when_disabled() -> None:
    engine = FuturesOrderSubmissionEngine(
        _StubClient(),
        FuturesLiveSafetyGate(enabled=False, dry_run=False, confirm_live=True),
    )

    result = engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
    )

    assert result.accepted is False
    assert result.reason == "safety_gate_disabled"


def test_gate_blocks_when_dry_run() -> None:
    engine = FuturesOrderSubmissionEngine(
        _StubClient(),
        FuturesLiveSafetyGate(enabled=True, dry_run=True, confirm_live=True),
    )

    result = engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
    )

    assert result.accepted is False
    assert result.dry_run is True
    assert result.status == "DRY_RUN"
    assert result.reason == "safety_gate_dry_run"


def test_gate_blocks_when_confirm_missing() -> None:
    engine = FuturesOrderSubmissionEngine(
        _StubClient(),
        FuturesLiveSafetyGate(enabled=True, dry_run=False, confirm_live=False),
    )

    result = engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
    )

    assert result.reason == "safety_gate_confirm_required"


def test_submit_order_success_returns_metadata() -> None:
    stub = _StubClient()
    stub.next_response = FuturesHttpResponse(
        status_code=200,
        body={
            "orderId": 987654321,
            "clientOrderId": "abc-123",
            "status": "FILLED",
            "executedQty": "0.01",
            "avgPrice": "60050.5",
        },
    )
    engine = FuturesOrderSubmissionEngine(stub, _open_gate())

    result = engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
            client_order_id="abc-123",
        )
    )

    assert result.accepted is True
    assert result.dry_run is False
    assert result.order_id == 987654321
    assert result.status == "FILLED"
    assert result.executed_qty == pytest.approx(0.01)
    assert result.avg_price == pytest.approx(60050.5)
    assert stub.calls[0][0] == "/fapi/v1/order"


def test_submit_order_wraps_binance_error() -> None:
    stub = _StubClient()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-2019,
        message="Margin is insufficient.",
        path="/fapi/v1/order",
    )
    engine = FuturesOrderSubmissionEngine(stub, _open_gate())

    result = engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
        )
    )

    assert result.accepted is False
    assert result.reason == "binance_error[-2019]: Margin is insufficient."


def test_submit_order_forwards_optional_params() -> None:
    stub = _StubClient()
    engine = FuturesOrderSubmissionEngine(stub, _open_gate())

    engine.submit_order(
        FuturesOrderRequest(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            close_position=True,
            stop_price=2000,
            working_type=WorkingType.MARK_PRICE,
            position_side=PositionSide.LONG,
        )
    )

    _, params = stub.calls[0]
    assert params["closePosition"] is True
    assert params["stopPrice"] == "2000"
    assert params["workingType"] == "MARK_PRICE"
    assert params["positionSide"] == "LONG"
    assert "quantity" not in params


def test_submit_order_limit_serializes_time_in_force() -> None:
    stub = _StubClient()
    engine = FuturesOrderSubmissionEngine(stub, _open_gate())

    engine.submit_order(
        FuturesOrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
            price=60000,
            time_in_force=TimeInForce.GTC,
            reduce_only=True,
        )
    )

    _, params = stub.calls[0]
    assert params["price"] == "60000"
    assert params["timeInForce"] == "GTC"
    assert params["reduceOnly"] is True

