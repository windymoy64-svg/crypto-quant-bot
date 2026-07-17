from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.client import FuturesHttpError, FuturesHttpResponse
from app.exchange.binance_futures.leverage import (
    FuturesLeverageManager,
    MarginType,
    PositionMode,
)


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.next_response: FuturesHttpResponse | Exception | None = None

    def post(self, path, params=None, *, signed=True):  # noqa: ARG002
        self.calls.append(("POST", path, dict(params or {})))
        response = self.next_response
        self.next_response = None
        if isinstance(response, Exception):
            raise response
        if response is None:
            return FuturesHttpResponse(status_code=200, body={})
        return response

    def get(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("get should not be called in leverage tests")

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("delete should not be called in leverage tests")


def _manager() -> tuple[FuturesLeverageManager, _StubClient]:
    stub = _StubClient()
    return FuturesLeverageManager(stub), stub


def test_set_leverage_posts_expected_payload() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpResponse(
        status_code=200,
        body={"leverage": 5, "maxNotionalValue": "1000000", "symbol": "BTCUSDT"},
    )

    result = manager.set_leverage("btcusdt", 5)

    assert stub.calls == [
        ("POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 5})
    ]
    assert result.symbol == "BTCUSDT"
    assert result.leverage == 5
    assert result.max_notional_value == "1000000"
    assert result.unchanged is False


def test_set_leverage_swallows_no_change_error() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-4028,
        message="Leverage not modified",
        path="/fapi/v1/leverage",
    )

    result = manager.set_leverage("BTCUSDT", 10)

    assert result.unchanged is True
    assert result.leverage == 10


def test_set_leverage_reraises_other_errors() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-1121,
        message="Invalid symbol",
        path="/fapi/v1/leverage",
    )

    with pytest.raises(FuturesHttpError):
        manager.set_leverage("BTCUSDT", 10)


def test_set_leverage_validates_range() -> None:
    manager, _ = _manager()

    with pytest.raises(ValueError):
        manager.set_leverage("BTCUSDT", 0)
    with pytest.raises(ValueError):
        manager.set_leverage("BTCUSDT", 200)
    with pytest.raises(ValueError):
        manager.set_leverage("", 5)


def test_set_margin_type_posts_isolated() -> None:
    manager, stub = _manager()

    result = manager.set_margin_type("btcusdt", MarginType.ISOLATED)

    assert stub.calls == [
        (
            "POST",
            "/fapi/v1/marginType",
            {"symbol": "BTCUSDT", "marginType": "ISOLATED"},
        )
    ]
    assert result.symbol == "BTCUSDT"
    assert result.margin_type is MarginType.ISOLATED
    assert result.unchanged is False


def test_set_margin_type_swallows_no_change_error() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-4046,
        message="No need to change margin type.",
        path="/fapi/v1/marginType",
    )

    result = manager.set_margin_type("BTCUSDT", MarginType.CROSSED)

    assert result.unchanged is True


def test_set_position_mode_hedge_sends_dual_side_true() -> None:
    manager, stub = _manager()

    result = manager.set_position_mode(PositionMode.HEDGE)

    assert stub.calls == [
        ("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": True})
    ]
    assert result.mode is PositionMode.HEDGE
    assert result.unchanged is False


def test_set_position_mode_swallows_no_change_error() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-4059,
        message="No need to change position side.",
        path="/fapi/v1/positionSide/dual",
    )

    result = manager.set_position_mode(PositionMode.ONE_WAY)

    assert result.unchanged is True


def test_set_multi_assets_margin_reports_change() -> None:
    manager, stub = _manager()

    changed = manager.set_multi_assets_margin(True)

    assert changed is True
    assert stub.calls == [
        ("POST", "/fapi/v1/multiAssetsMargin", {"multiAssetsMargin": True})
    ]


def test_set_multi_assets_margin_swallows_no_change_error() -> None:
    manager, stub = _manager()
    stub.next_response = FuturesHttpError(
        status_code=400,
        code=-4171,
        message="Multi-Assets Mode not modified.",
        path="/fapi/v1/multiAssetsMargin",
    )

    assert manager.set_multi_assets_margin(False) is False
